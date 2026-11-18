"""YOLOX Nano ONNX CPU 推理适配器，遵循上游的非 legacy 预处理约定。

YOLOX 0.1.1rc0 使用 [0,255] 范围的 BGR float32、左上角 letterbox、
padding=114 和原始 stride 网格输出；改成 RGB 或除以 255 都会破坏模型约定。

本模块是模型适配边界：上游只传入 BGR 图像，下游只接收 ``Detection``。
预处理、YOLOX 网格解码、person 置信度计算和 NMS 都留在这里，流水线
不需要知道 ONNX 输出张量的形状。

推理阶段的顺序固定为：保持 BGR 约定 → 左上角填充到模型尺寸 → 运行 ONNX
→ 用 stride 网格还原框 → 过滤 person 置信度 → NMS。任何一步的坐标约定变化
都必须在本模块内完成，不能让流水线猜测模型细节。
"""
from functools import lru_cache
from pathlib import Path
import time
import cv2
import numpy as np
import onnxruntime as ort
from .types import Detection


class DetectorError(RuntimeError):
    """模型文件、输入形状或推理执行不符合适配器约定时的异常。"""
    pass


def preprocess(image, size):
    """按 YOLOX 约定做左上角 letterbox，并返回张量和缩放比例。"""
    # 模型要求固定尺寸，但检测框最后要回到原图；ratio 是两套坐标之间的桥梁。
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise DetectorError("Expected HxWx3 BGR image")
    height, width = image.shape[:2]
    ratio = min(size[0] / height, size[1] / width)
    # 只缩放不裁剪，剩余区域用 YOLOX 约定的 114 填充，并保持原始 BGR 数值范围。
    resized = cv2.resize(image,
                         (int(width * ratio),
                          int(height * ratio)),
                         interpolation=cv2.INTER_LINEAR)
    padded = np.full((size[0], size[1], 3), 114, dtype=np.uint8)
    padded[:resized.shape[0], :resized.shape[1]] = resized
    return np.ascontiguousarray(padded.transpose(
        2, 0, 1)[None], dtype=np.float32), ratio


@lru_cache(maxsize=4)
def _decode_grid(size):
    # 三个 stride 的网格共同构成 YOLOX 的输出位置；网格顺序必须和模型张量一致。
    grids = []
    steps = []
    for s in (8, 16, 32):
        x, y = np.meshgrid(np.arange(size[1] // s), np.arange(size[0] // s))
        grids.append(np.stack([x, y], axis=-1).reshape(-1, 2))
        steps.append(np.full((x.size, 1), s))
    grid = np.concatenate(grids)
    stride = np.concatenate(steps)
    grid.flags.writeable = False
    stride.flags.writeable = False
    return grid, stride


def postprocess(raw, size, image_shape, ratio, confidence=.35, nms=.45):
    """把原始网格输出解码为裁剪到原图边界的 person 检测框。"""
    grid, stride = _decode_grid(tuple(size))
    if raw.shape != (1, len(grid), 85):
        raise DetectorError(
            f"Expected raw YOLOX [1,{len(grid)},85], got {raw.shape}")
    # 形状检查在解码前失败，避免模型文件不匹配时产生静默的错误框。
    pred = raw[0]
    # YOLOX 的 person 分数是 objectness 与 COCO person 类别概率的乘积。
    scores = pred[:, 4] * pred[:, 5]
    # 与上游最高类别选择一致，避免其他类别更可信时仍输出人体框。
    indices = np.flatnonzero(scores >= confidence)
    if not indices.size:
        return []
    candidates = pred[indices]
    valid = (np.argmax(candidates[:, 5:], axis=1) == 0) & np.isfinite(candidates).all(axis=1)
    indices = indices[valid]
    if not indices.size:
        return []
    selected = pred[indices]
    scores = scores[indices]
    steps = stride[indices]
    center = (selected[:, :2] + grid[indices]) * steps
    wh = np.exp(np.clip(selected[:, 2:4], -16, 16)) * steps
    boxes = np.concatenate([center - wh / 2, center + wh / 2], axis=1) / ratio
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, image_shape[1])
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, image_shape[0])
    valid = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    boxes = boxes[valid]
    scores = scores[valid]
    xywh = boxes.copy()
    xywh[:, 2:] -= xywh[:, :2]
    # NMS 只接收有效框，抑制同一个人被相邻网格重复报告的结果。
    keep = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), confidence, nms)
    return [Detection(*map(float, boxes[i]), float(scores[i]), "person")
            for i in np.asarray(keep).flatten()]


class Detector:
    """固定输入尺寸的 ONNX Runtime CPU 推理适配器。"""

    def __init__(self, model_path, threads=2, confidence=.35, nms=.45):
        # 在启动阶段验证模型和固定输入形状，让运行中的 detect() 可以保持简单。
        self.path = Path(model_path)
        if not self.path.is_file():
            raise DetectorError(f"Model file not found: {self.path}")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        try:
            self.session = ort.InferenceSession(
                str(self.path), sess_options=options, providers=["CPUExecutionProvider"])
            info = self.session.get_inputs()[0]
            if len(info.shape) != 4 or not all(isinstance(n, int)
                                               for n in info.shape[-2:]):
                raise DetectorError(
                    "This adapter requires fixed NCHW YOLOX input")
            self.name = info.name
            self.size = tuple(info.shape[-2:])
        except Exception as exc:
            raise DetectorError(f"{self.path}: {exc}") from exc
        self.last_inference_ms = 0.
        self.confidence = confidence
        self.nms = nms

    def detect(self, image):
        """完成一次预处理、推理和后处理，并记录模型耗时（毫秒）。"""
        # 只把 ONNX Runtime 的计算时间计入模型耗时，预处理和后处理仍由端到端指标覆盖。
        tensor, ratio = preprocess(image, self.size)
        start = time.perf_counter()
        output = self.session.run(None, {self.name: tensor})[0]
        self.last_inference_ms = (time.perf_counter() - start) * 1000
        return postprocess(
            output,
            self.size,
            image.shape,
            ratio,
            self.confidence,
            self.nms)

    @property
    def confidence(self):
        return self._confidence

    @confidence.setter
    def confidence(self, value):
        self._confidence = value
