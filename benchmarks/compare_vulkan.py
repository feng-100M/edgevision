"""Benchmark EdgeVision's detector on the Pi 5 using identical video frames."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from time import perf_counter

import cv2
import numpy as np
import onnxruntime

from edgevision.assets import ASSETS, verify, verify_model
from edgevision.detector import Detector, postprocess, preprocess
from edgevision.geometry import iou


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/gpu-benchmark"
MODEL = ROOT / "models/yolox_nano_320.onnx"
VIDEO = ROOT / "data/videos/vtest.avi"
CONVERTED = CACHE / "yolox320-fp32"
PARAM = CONVERTED / "yolox_nano_320.ncnn.param"
WEIGHTS = CONVERTED / "yolox_nano_320.ncnn.bin"
BACKENDS = ("ort-cpu", "ncnn-cpu", "ncnn-vulkan")
SIZE = (320, 320)
THREADS = 2
CONFIDENCE = .35
NMS = .45
MATCH_IOU = .50


def rewrite_focus(param):
    """Replace pnnx's unsupported strided slices with equivalent ncnn layers."""
    lines = param.splitlines()
    expected = (
        "Input in0 0 1 in0",
        "Split splitncnn_0 1 4 in0 1 2 3 4",
        "Tensor.slice Tensor.slice_23 1 1 4 5",
        "Tensor.slice Tensor.slice_25 1 1 3 6",
        "Tensor.slice Tensor.slice_27 1 1 2 7",
        "Tensor.slice Tensor.slice_29 1 1 1 8",
        "Concat cat_0 4 1 5 7 6 8 9 0=0",
    )
    if not lines or lines[0] != "7767517" or tuple(
            " ".join(line.split()) for line in lines[2:9]) != expected:
        raise ValueError("Unexpected pnnx YOLOX Focus graph. Check model and converter versions.")
    layers, blobs = map(int, lines[1].split())
    # Reorg emits TL, TR, BL, BR. Focus feeds the convolution TL, BL, TR, BR.
    focus = (
        "Reorg focus_reorg 1 1 in0 1 0=2 1=1",
        "Slice focus_split 1 4 1 2 3 4 5 -23300=4,3,3,3,3 1=0",
        "Concat focus_concat 4 1 2 4 3 5 9 0=0",
    )
    return "\n".join([lines[0], f"{layers - 3} {blobs - 3}", lines[2],
                      *focus, *lines[9:]]) + "\n"


def prepare_model():
    if CACHE.resolve() != CACHE or CONVERTED.resolve() != CONVERTED:
        raise ValueError("GPU benchmark cache must be inside the project")
    if PARAM.is_file() and WEIGHTS.is_file():
        return
    converter = CACHE / "python/pnnx/pnnx"
    if not converter.is_file():
        raise ValueError("Install the benchmark dependencies from benchmarks/README.md")
    with tempfile.TemporaryDirectory(dir=CACHE, prefix="convert-") as directory:
        work = Path(directory)
        shutil.copyfile(MODEL, work / MODEL.name)
        subprocess.run([str(converter), MODEL.name, "fp16=0"], cwd=work, check=True)
        output = work / "model"
        output.mkdir()
        param = rewrite_focus((work / PARAM.name).read_text(encoding="utf-8"))
        (output / PARAM.name).write_text(param, encoding="utf-8")
        (work / WEIGHTS.name).rename(output / WEIGHTS.name)
        try:
            output.rename(CONVERTED)
        except OSError:
            # A concurrent preparation can publish the same pair first.
            if not (PARAM.is_file() and WEIGHTS.is_file()):
                raise


@contextmanager
def load_backend(name):
    if name == "ort-cpu":
        detector = Detector(MODEL, threads=THREADS)
        if detector.size != SIZE:
            raise ValueError(f"Unexpected model input: {detector.size}")

        def infer(tensor):
            return detector.session.run(None, {detector.name: tensor})[0]

        yield infer, {"version": onnxruntime.__version__, "device": "CPUExecutionProvider"}
        return

    import ncnn

    with ncnn.Net() as net:
        net.opt.num_threads = THREADS
        net.opt.use_fp16_packed = False
        net.opt.use_fp16_storage = False
        net.opt.use_fp16_arithmetic = False
        net.opt.use_bf16_packed = False
        net.opt.use_bf16_storage = False
        net.opt.use_int8_inference = False
        vulkan = name == "ncnn-vulkan"
        device_name = "CPU"
        if vulkan:
            if ncnn.get_gpu_count() != 1:
                raise RuntimeError("Expected exactly one GPU. Select the Pi Broadcom Vulkan ICD.")
            device = ncnn.get_gpu_device(0).info()
            device_name = device.device_name()
            if device.vendor_id() != 0x14e4 or not device_name.startswith("V3D "):
                raise RuntimeError(f"Expected the Pi hardware GPU, got {device_name}")
            net.set_vulkan_device(0)
        net.opt.use_vulkan_compute = vulkan
        if net.load_param(str(PARAM)) != 0 or net.load_model(str(WEIGHTS)) != 0:
            raise RuntimeError("Cannot load the benchmark ncnn model")
        if net.opt.use_vulkan_compute != vulkan:
            raise RuntimeError("ncnn did not retain the requested Vulkan setting")
        input_name, = net.input_names()
        output_name, = net.output_names()

        def infer(tensor):
            with net.create_extractor() as extractor:
                if extractor.input(input_name, ncnn.Mat(tensor, batch_index=0).clone()) != 0:
                    raise RuntimeError("ncnn input failed")
                status, output = extractor.extract(output_name)
                if status != 0 or output.empty():
                    raise RuntimeError(f"ncnn extraction failed ({status})")
                # Read back the completed output while the extractor still owns it.
                return output.numpy(batch_index=0).copy()

        yield infer, {"version": ncnn.__version__, "device": device_name}


def read_frames(count, stride):
    capture = cv2.VideoCapture(str(VIDEO))
    try:
        frames = []
        for index in range((count - 1) * stride + 1):
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f"Cannot read video frame {index}. Reduce --frames or --stride.")
            if index % stride == 0:
                frames.append(frame)
        return frames
    finally:
        capture.release()


def detect(infer, frame):
    started = perf_counter()
    tensor, ratio = preprocess(frame, SIZE)
    inference_started = perf_counter()
    output = infer(tensor)
    model_ms = (perf_counter() - inference_started) * 1000
    if output.dtype != np.float32 or not np.isfinite(output).all():
        raise RuntimeError("Expected finite FP32 model output")
    boxes = postprocess(output, SIZE, frame.shape, ratio, CONFIDENCE, NMS)
    return boxes, model_ms, (perf_counter() - started) * 1000


def trial(name, frames, warmup):
    with load_backend(name) as (infer, backend):
        for index in range(warmup):
            detect(infer, frames[index % len(frames)])
        boxes, model_ms, detector_ms = zip(*(detect(infer, frame) for frame in frames))
        return boxes, {**backend, "model_ms": model_ms, "detector_ms": detector_ms,
                       "box_counts": [len(frame) for frame in boxes]}


def compare_detections(reference, candidate):
    matched = []
    score_deltas = []
    for first, second in zip(reference, candidate, strict=True):
        pairs = sorted(((iou(a.bbox, b.bbox), i, j)
                        for i, a in enumerate(first) for j, b in enumerate(second)),
                       reverse=True)
        used_first, used_second = set(), set()
        for overlap, i, j in pairs:
            if overlap < MATCH_IOU:
                break
            if i not in used_first and j not in used_second:
                used_first.add(i)
                used_second.add(j)
                matched.append(overlap)
                score_deltas.append(abs(first[i].confidence - second[j].confidence))
    return {"matched_boxes": len(matched),
            "unmatched_reference_boxes": sum(map(len, reference)) - len(matched),
            "unmatched_candidate_boxes": sum(map(len, candidate)) - len(matched),
            "minimum_matched_iou": min(matched, default=None),
            "maximum_matched_confidence_delta": max(score_deltas, default=None)}


def summarize(values):
    p50, p95 = np.percentile(values, [50, 95])
    return {"p50_ms": float(p50), "p95_ms": float(p95),
            "sequential_fps": 1000 / float(np.mean(values))}


def board_status():
    if not shutil.which("vcgencmd"):
        return {}
    return {name: subprocess.check_output(["vcgencmd", name], text=True).strip()
            for name in ("measure_temp", "get_throttled")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Convert the pinned ONNX model to ncnn")
    parser.add_argument("--backend", choices=("all", *BACKENDS), default="all")
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--stride", type=int, default=18)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()
    if min(args.frames, args.stride, args.rounds, args.warmup) < 1:
        parser.error("frames, stride, rounds and warmup must be positive")

    model_sha256 = verify_model(MODEL, ROOT)
    if args.prepare:
        prepare_model()
        return
    names = BACKENDS if args.backend == "all" else (args.backend,)
    converted_hashes = {}
    if any(name != "ort-cpu" for name in names):
        if not (PARAM.is_file() and WEIGHTS.is_file()):
            parser.error("Run with --prepare before benchmarking ncnn")
        for path in (PARAM, WEIGHTS):
            with path.open("rb") as source:
                converted_hashes[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
    os.environ.setdefault("VK_ICD_FILENAMES", "/usr/share/vulkan/icd.d/broadcom_icd.aarch64.json")
    os.environ["MESA_SHADER_CACHE_DISABLE"] = "true"
    video_sha256 = verify(VIDEO, ASSETS["data/videos/vtest.avi"][1])
    cv2.setNumThreads(1)
    frames = read_frames(args.frames, args.stride)
    report = {
        "platform": platform.platform(), "opencv_version": cv2.__version__,
        "model_sha256": model_sha256, "converted_model_sha256": converted_hashes,
        "video_sha256": video_sha256, "frame_shape": frames[0].shape,
        "frame_indices": list(range(0, args.frames * args.stride, args.stride)),
        "model_size": SIZE, "precision": "FP32", "threads": THREADS,
        "confidence": CONFIDENCE, "nms": NMS, "match_iou": MATCH_IOU,
        "warmup_per_trial": args.warmup, "rounds": [], "summary": {},
    }
    for index in range(args.rounds):
        offset = index % len(names)
        order = names[offset:] + names[:offset]
        detections, trials = {}, {}
        for name in order:
            before = board_status()
            detections[name], trials[name] = trial(name, frames, args.warmup)
            trials[name].update(board_before=before, board_after=board_status())
        agreement = {name: compare_detections(detections["ort-cpu"], detections[name])
                     for name in names[1:]}
        report["rounds"].append({"order": order, "trials": trials, "vs_ort_cpu": agreement})
    for name in names:
        trials = [item["trials"][name] for item in report["rounds"]]
        report["summary"][name] = {key: summarize([value for run in trials for value in run[key]])
                                   for key in ("model_ms", "detector_ms")}
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
