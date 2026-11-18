"""固定机位上的轻量、确定性人员跟踪器。

跟踪器接收单帧检测，输出带稳定 ID 的短时轨迹；它不负责产生进入/离开事件。
事件模块只使用这里返回的 ID 和框，因此一次漏检不应立刻导致轨迹被遗忘。
"""

from __future__ import annotations

from collections.abc import Sequence
import math

from .geometry import iou
from .types import Detection, Track


class CentroidIoUTracker:
    """使用 IoU 和按图像对角线归一化的质心距离进行匹配。

    候选只要重叠足够或距离足够近即可通过，再按综合代价贪心分配，稳定的
    轨迹 ID 用于打破平局。这个轻量实现不建模外观特征和遮挡。

    先按候选代价做贪心一对一匹配，再为未匹配检测分配新 ID；短暂漏检
    由 ``max_age_frames`` 保留。它适合固定机位的单类别入侵判断，不能
    代替带外观特征和 Kalman 预测的完整多目标跟踪器。
    """

    def __init__(
            self,
            max_age_frames: int = 5,
            iou_threshold: float = .2,
            max_centroid_distance: float = .15) -> None:
        if not isinstance(max_age_frames, int) or max_age_frames < 0:
            raise ValueError("max_age_frames must be a nonnegative integer")
        if not math.isfinite(iou_threshold) or not 0 <= iou_threshold <= 1:
            raise ValueError("iou_threshold must be between zero and one")
        if not math.isfinite(
                max_centroid_distance) or max_centroid_distance < 0:
            raise ValueError(
                "max_centroid_distance must be finite and nonnegative")
        self.max_age_frames = max_age_frames
        self.iou_threshold = iou_threshold
        self.max_centroid_distance = max_centroid_distance
        self._tracks: dict[int, Track] = {}
        self._next_id = 1
        self._last_timestamp: float | None = None

    @property
    def active_tracks(self) -> tuple[Track, ...]:
        """返回当前观测到以及短暂漏检但仍保留用于重关联的轨迹。"""
        return tuple(self._tracks.values())

    def update(
            self,
            detections: Sequence[Detection],
            timestamp: float,
            image_shape: Sequence[int]) -> list[Track]:
        """用当前帧检测更新轨迹并返回本帧实际观测到的轨迹。

        ``timestamp`` 必须单调递增；``image_shape`` 用来把质心距离除以
        图像对角线，使同一个阈值在不同分辨率下含义近似一致。
        """
        # 时间戳必须单调，否则漏检保留和轨迹过期都会得到错误结果。
        if not math.isfinite(timestamp) or (
                self._last_timestamp is not None and timestamp < self._last_timestamp):
            raise ValueError(
                "Tracker timestamps must be finite and nondecreasing")
        if len(image_shape) < 2 or not all(math.isfinite(value)
                                           and value > 0 for value in image_shape[:2]):
            raise ValueError("image_shape must have positive height and width")
        height, width = image_shape[:2]
        diagonal = math.hypot(width, height)
        candidates: list[tuple[float, int, int]] = []

        # 为每条旧轨迹建立候选匹配：同类别且满足 IoU 或质心距离阈值才进入竞争。
        for track_id, track in self._tracks.items():
            previous = track.detection
            px = (previous.x1 + previous.x2) / 2
            py = (previous.y1 + previous.y2) / 2
            for index, detection in enumerate(detections):
                if previous.class_name != detection.class_name:
                    continue
                dx = (detection.x1 + detection.x2) / 2 - px
                dy = (detection.y1 + detection.y2) / 2 - py
                distance = math.hypot(dx, dy) / diagonal
                overlap = iou(previous.bbox, detection.bbox)
                if overlap >= self.iou_threshold or distance <= self.max_centroid_distance:
                    candidates.append(
                        (1.0 - overlap + distance, track_id, index))

        # 按综合代价排序后贪心分配，保证一条旧轨迹和一个新检测不会被重复使用。
        matched_tracks: set[int] = set()
        assignments: dict[int, int] = {}
        for _, track_id, index in sorted(candidates):
            if track_id not in matched_tracks and index not in assignments:
                matched_tracks.add(track_id)
                assignments[index] = track_id

        # 未匹配轨迹只增加 missed 计数；短暂漏检期间保留它们，下一帧仍可接回原 ID。
        retained = {
            track_id: Track(track_id, track.detection, track.last_seen, track.missed + 1)
            for track_id, track in self._tracks.items()
            if track_id not in matched_tracks and track.missed < self.max_age_frames
        }
        # 未匹配检测获得新 ID，匹配检测沿用旧 ID；返回值只包含本帧实际观测到的轨迹。
        observed = []
        for index, detection in enumerate(detections):
            track_id = assignments.get(index)
            if track_id is None:
                track_id = self._next_id
                self._next_id += 1
            track = Track(track_id, detection, timestamp)
            retained[track_id] = track
            observed.append(track)
        self._tracks = dict(sorted(retained.items()))
        self._last_timestamp = timestamp
        return observed
