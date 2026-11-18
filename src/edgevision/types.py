"""采集、检测和事件阶段之间传递的最小数据契约。

这些数据类是学习本项目时最值得先读的一组类型：输入帧变成
``Detection``，检测经过短时关联变成 ``Track``，状态变化最终形成
``Event``。它们只描述数据，不负责调用摄像头、模型或外部服务。

整条链路共享这些对象，因此这里的约束决定了后续模块可以放心假设什么：
检测框必须有正面积，时间字段分别服务于实时延迟和回放定位，事件则必须
能够直接转换成 JSON。把这些约束放在数据边界上，可以避免每个消费者重复防御。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class Detection:
    """一个检测框；坐标使用原始图像的像素坐标，类别首版固定为 person。"""
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_name: str = "person"

    def __post_init__(self) -> None:
        # 检测结果一旦进入跟踪器，就默认坐标和置信度可参与距离、面积等计算。
        # 因此在对象创建时拒绝 NaN、无穷值和反向框，避免错误沿流水线扩散。
        if not all(math.isfinite(value)
                   for value in (*self.bbox, self.confidence)):
            raise ValueError(
                "Detection coordinates and confidence must be finite")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("Detection must have positive width and height")
        if not 0 <= self.confidence <= 1:
            raise ValueError(
                "Detection confidence must be between zero and one")

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        # 统一返回不可变的四元组，让几何、跟踪和存储模块使用同一种框表示。
        return (self.x1, self.y1, self.x2, self.y2)


@dataclass(slots=True)
class Frame:
    """采集阶段交给流水线的图像及其两种时间。

    ``captured_at`` 是本机单调时钟，用来测端到端延迟；``source_time``
    是回放文件中的媒体时间，只有回放有意义，不能拿它替代实时系统时钟。
    """
    seq: int
    captured_at: float
    image: Any
    source_name: str
    source_time: float | None = 0.0


@dataclass(frozen=True, slots=True)
class Track:
    """把相邻帧中的检测框关联成的短生命周期轨迹。"""
    track_id: int
    detection: Detection
    last_seen: float
    missed: int = 0


@dataclass(slots=True)
class Event:
    """对外输出的进入/离开事件；截图路径在本地保存成功后才会填入。"""
    event_id: str
    event_type: str
    occurred_at: str
    confidence: float
    roi_name: str
    bbox: tuple[float, float, float, float]
    snapshot_path: str | None
    source_name: str
    track_id: int
    source_time: float | None = 0.0
    snapshot_note: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """返回可安全写入 JSON 的字典，并转换 NumPy 标量检测值。"""
        # JSONL 和 MQTT 共用同一份字典，转换 NumPy 标量和元组后才能稳定序列化。
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "confidence": float(
                self.confidence),
            "roi_name": self.roi_name,
            "bbox": [
                float(value) for value in self.bbox],
            "snapshot_path": self.snapshot_path,
            "source_name": self.source_name,
            "track_id": int(
                self.track_id),
            "source_time": None if self.source_time is None else float(
                self.source_time),
            "snapshot_note": self.snapshot_note,
        }
