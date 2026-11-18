"""命令行入口；所有生成文件都限制在项目目录内。

CLI 是学习和验收的外层入口：``infer`` 验证单图模型，``replay`` 验证
离线流水线，``run`` 才会打开实时输入，``check`` 只检查输入设备。

所有子命令共享同一条路径边界和配置加载逻辑；这样离线练习、设备检查和
长期运行产生的结果都不会写出项目目录，也不会绕过模型校验。
"""
import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import signal
import sys
import threading
import time
import cv2
import numpy as np
from .assets import download_assets, verify_model
from .config import load_config, ConfigError
from .detector import Detector, DetectorError
from .pipeline import Pipeline
from .sources import VideoFileSource, UvcCameraSource, SourceError, orient_image

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def read_image(path):
    """以 OpenCV BGR 格式读取一张本地图片。"""
    # infer 的输入先经过这里，确保后续 detector 始终看到三通道 BGR 图像。
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Cannot read image: {path}")
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    return image


def output_path(value, root):
    """解析输出路径并拒绝写到项目目录之外。"""
    # 所有 CLI 生成物共用这个检查，避免不同子命令各自实现路径安全规则。
    root = Path(root).resolve()
    p = (root / Path(value)).resolve()
    if not p.is_relative_to(root):
        raise ValueError(
            f"Output must remain inside project directory: {root}")
    return p


def emit(result, destination, root):
    """同时打印 JSON，并按需在项目内写出一份结果文件。"""
    # 终端输出和 JSON 文件使用同一份序列化结果，便于学习时复制和复核。
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if destination:
        p = output_path(destination, root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")
    print(text)


def parser():
    """构造所有子命令的参数解析器。"""
    # 参数解析只描述命令边界；真正的输入选择和资源生命周期集中在 _main。
    p = argparse.ArgumentParser(
        description="Offline EdgeVision person intrusion detection")
    sub = p.add_subparsers(dest="command", required=True)
    for name in (
        "check",
        "infer",
        "replay",
        "run",
        "benchmark",
        "assets",
            "model-manifest"):
        s = sub.add_parser(name)
        s.add_argument(
            "--config",
            default=str(
                DEFAULT_ROOT /
                "config.example.yaml"))
        s.add_argument("--json-out", "--output", dest="json_out")
        if name in ("check", "replay", "run", "benchmark"):
            s.add_argument("--input", choices=["video", "uvc"])
            s.add_argument("--video")
            s.add_argument("--device")
            s.add_argument("--duration", type=float)
            s.add_argument("--frames", type=int)
            s.add_argument("--loop", action="store_true")
            s.add_argument(
                "--fast",
                action="store_true",
                help="Decode file as fast as possible, offline throughput only")
            s.add_argument(
                "--mode",
                choices=[
                    "sync",
                    "latest"],
                default="latest")
            s.add_argument("--trace", help="Per-frame raw CSV inside project")
            s.add_argument("--threads", type=int)
            s.add_argument("--no-mqtt", action="store_true")
            s.add_argument(
                "--preview",
                action="store_true",
                help="Loopback-only live view with ROI and tracks")
            s.add_argument("--preview-port", type=int, default=8765)
        if name == "infer":
            s.add_argument("--image", required=True)
            s.add_argument("--model")
            s.add_argument(
                "--annotated",
                help="Save ROI and detection overlay inside project")
        if name == "check":
            s.add_argument(
                "--snapshot",
                help="Save the last captured frame inside project")
    return p


def _main(args):
    """执行已解析的命令；这里集中处理路径、模型校验和输入选择。"""
    # 先锁定项目根和配置，再允许具体子命令读取模型、视频或摄像头。
    root = DEFAULT_ROOT.resolve()
    if not Path(args.config).resolve().is_relative_to(root):
        raise ValueError("Configuration must stay inside project directory")
    cfg = load_config(args.config)
    # 即使用户传入自定义 YAML，也强制输出目录留在项目写入边界内。
    output_path(cfg.output.directory, root)
    if args.json_out:
        output_path(args.json_out, root)
    cv2.setNumThreads(1)

    # 资产和模型清单命令不启动检测流水线，只执行下载/校验后立即返回。
    if args.command == "assets":
        emit(download_assets(root), args.json_out, root)
        return 0
    if args.command == "model-manifest":
        result = {
            "path": str(
                cfg.model.path), "sha256": verify_model(
                cfg.model.path, root)}
        emit(result, args.json_out, root)
        return 0
    if args.command == "infer":
        # 单图命令只验证预处理、ONNX 推理和后处理，不涉及线程、事件或 MQTT。
        image = read_image(root / args.image)
        model = Path(args.model) if args.model else cfg.model.path
        if not model.is_absolute():
            model = root / model
        model_digest = verify_model(model, root)
        detector = Detector(
            model,
            cfg.model.threads,
            cfg.model.confidence,
            cfg.model.nms)
        detections = detector.detect(image)
        if args.annotated:
            destination = output_path(args.annotated, root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if cfg.roi.enabled:
                polygon = np.array([(p[0] * image.shape[1], p[1] * image.shape[0])
                                    for p in cfg.roi.points], np.int32)
                cv2.polylines(image, [polygon], True, (255, 100, 0), 2)
            for d in detections:
                x1, y1, x2, y2 = map(int, d.bbox)
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 220, 0), 2)
                cv2.circle(image, (int((x1 + x2) / 2), y2), 4, (0, 0, 255), -1)
            ok, buffer = cv2.imencode(".jpg", image)
            if not ok:
                raise ValueError("Cannot encode annotated image")
            destination.write_bytes(buffer.tobytes())
        emit({"detections": [asdict(d) for d in detections],
              "inference_ms": detector.last_inference_ms,
              "image_shape": list(image.shape),
              "model_input": list(detector.size),
              "model_sha256": model_digest},
             args.json_out,
             root)
        return 0
    if args.duration is not None and args.duration <= 0:
        raise ValueError("duration must be positive")
    if args.frames is not None and args.frames <= 0:
        raise ValueError("frames must be positive")
    # replay 默认走视频，run 默认沿用配置；显式 --input 可以覆盖这个选择。
    kind = args.input or ("video" if args.command ==
                          "replay" else cfg.input.type)
    if kind == "uvc":
        source = UvcCameraSource(
            args.device or cfg.input.device,
            cfg.input.width,
            cfg.input.height,
            cfg.input.fps,
            cfg.input.retry_seconds,
            cfg.input.focus_warmup_frames)
    else:
        source = VideoFileSource(
            root / args.video if args.video else cfg.input.path,
            realtime=not args.fast,
            loop=args.loop)
    if args.command == "check":
        # check 只读取并统计输入，不创建 Detector/Storage，适合先排查设备和方向。
        duration = args.duration or 10
        timer = threading.Timer(duration, source.close)
        timer.daemon = True
        timer.start()
        start = time.monotonic()
        count = 0
        shape = None
        try:
            for frame in source:
                frame.image = orient_image(
                    frame.image,
                    cfg.input.rotation,
                    cfg.input.mirror_horizontal)
                shape = list(frame.image.shape)
                count += 1
                if args.frames and count >= args.frames:
                    break
        finally:
            source.close()
            timer.cancel()
        snapshot_saved = False
        focus_score = None
        if count:
            gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
            focus_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if args.snapshot and count and focus_score >= cfg.input.min_sharpness:
            destination = output_path(args.snapshot, root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            ok, buffer = cv2.imencode(".jpg", frame.image)
            if not ok:
                raise ValueError("Cannot encode camera snapshot")
            destination.write_bytes(buffer.tobytes())
            snapshot_saved = True
        elapsed = time.monotonic() - start
        result = {"frames": count,
                  "seconds": elapsed,
                  "capture_fps": count / max(elapsed,
                                             .001),
                  "image_shape": shape,
                  "input_rotation": cfg.input.rotation,
                  "input_mirror_horizontal": cfg.input.mirror_horizontal,
                  "reconnects": getattr(source,
                                        "reconnects",
                                        0),
                  "focus_score": focus_score,
                  "snapshot_saved": snapshot_saved,
                  "snapshot_skipped": bool(args.snapshot and count and not snapshot_saved)}
        emit(result, args.json_out, root)
        return 0 if count else 2
    if args.threads is not None:
        if args.threads < 1:
            raise ValueError("threads must be positive")
        cfg.model.threads = args.threads
    if args.no_mqtt:
        cfg.mqtt.enabled = False
    # replay/run 共用完整 Pipeline，区别只来自输入源和命令行的节奏参数。
    model_digest = verify_model(cfg.model.path, root)
    detector = Detector(
        cfg.model.path,
        cfg.model.threads,
        cfg.model.confidence,
        cfg.model.nms)
    pipeline = Pipeline(cfg, source, detector)
    preview = None
    if args.preview:
        # 预览只作为流水线旁路启动，停止按钮通过 pipeline.stop() 结束本次运行。
        from .preview import PreviewServer
        preview = PreviewServer(args.preview_port, on_stop=pipeline.stop,
                                event_store=pipeline.storage, mqtt_status=pipeline.mqtt.status)
        pipeline.preview = preview
        logging.info("Live preview: %s", preview.url)

    def interrupt(signum, frame):
        # 信号回调只设置停止标记，不在信号上下文里执行文件或网络清理。
        pipeline.stop()
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        # 信号处理器只发出停止请求，真正的清理由 Pipeline.run 的 finally 统一完成。
        result = pipeline.run(
            mode=args.mode,
            max_frames=args.frames,
            duration=args.duration,
            trace_path=output_path(
                args.trace,
                root) if args.trace else None)
    finally:
        if preview:
            preview.close()
    result["preview_enabled"] = bool(args.preview)
    result.update({"model": cfg.model.path.name,
                   "model_sha256": model_digest,
                   "model_input": list(detector.size),
                   "ort_threads": cfg.model.threads,
                   "confidence": cfg.model.confidence,
                   "nms": cfg.model.nms,
                   "realtime": not args.fast,
                   "source": kind,
                   "roi_enabled": cfg.roi.enabled,
                   "roi": pipeline.active_roi_points or cfg.roi.points})
    emit(result, args.json_out, root)
    return 0 if result["processed_frames"] > 0 else 2


def main(argv=None):
    """把配置/设备/推理错误转换为稳定的 CLI 退出码。"""
    # CLI 在最外层把预期运行错误转换为退出码 2，保留日志而不打印 Python 堆栈。
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    try:
        return _main(args)
    except (ConfigError, DetectorError, SourceError, ValueError, OSError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
