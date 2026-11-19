"""ROI 进入/离开状态机，维护每条轨迹的冷却和过期状态。

这里把“每帧检测到一个框”提升为跨帧语义：同一轨迹在区域内持续存在时只
触发一次进入，短暂漏检不产生离开，只有真正观察到区域外状态才可能发出离开。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from uuid import uuid4

import cv2
import numpy as np

from .geometry import bottom_center, point_in_polygon
from .types import Event, Track


@dataclass(slots=True)
class _TrackState:
    inside: bool | None
    last_seen: float
    last_enter: float | None = None
    reason_inside: str = "inside_observed"
    candidate: bool | None = None
    observations: int = 0
    frame: int = -1


class EventEngine:
    """把轨迹底部中心点的 ROI 状态变化转换为事件。

    它只处理状态机，不负责截图、JSONL 或 MQTT。这样事件规则可以在
    没有摄像头和网络的单元测试中独立验证。
    """

    def __init__(self,
                 roi_name: str,
                 polygon: Sequence[Sequence[float]],
                 cooldown_seconds: float = 2.,
                 emit_leave: bool = True,
                 state_timeout_seconds: float = 5., *,
                 full_frame: bool = False, confirmation_confidence: float = .70) -> None:
        if not math.isfinite(cooldown_seconds) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be finite and nonnegative")
        if not math.isfinite(
                state_timeout_seconds) or state_timeout_seconds <= 0:
            raise ValueError(
                "state_timeout_seconds must be finite and positive")
        # 构造时验证多边形，避免运行到第一帧才发现 ROI 无效。
        point_in_polygon((0, 0), polygon)
        self.roi_name = roi_name
        self.polygon = tuple(tuple(float(value)
                             for value in vertex) for vertex in polygon)
        if not 0 < confirmation_confidence <= 1:
            raise ValueError("confirmation_confidence must be in (0,1]")
        self.confirmation_confidence = confirmation_confidence
        self.full_frame = full_frame
        self._contour = np.array(self.polygon, dtype=np.float32)
        self._frame = 0
        self.cooldown_seconds = cooldown_seconds
        self.emit_leave = emit_leave
        # 即使调用方给了更短的漏检过期时间，也不能让冷却状态提前消失。
        self.state_timeout_seconds = max(
            state_timeout_seconds, cooldown_seconds)
        self._states: dict[int, _TrackState] = {}
        self._last_timestamp: float | None = None
        self.diagnostics: list[dict] = []

    @property
    def state_count(self) -> int:
        return len(self._states)

    def update(
            self,
            tracks: Sequence[Track],
            timestamp: float,
            source_name: str = "",
            source_time: float | None = 0.) -> list[Event]:
        """用单调时间推进状态，并用独立的 UTC 时钟记录事件。

        短暂漏检会保留上一次 inside 状态；状态过期只删除记录，不凭空生成离开事件。

        进入事件受冷却窗口限制，离开事件由 ``emit_leave`` 控制；轨迹
        短暂消失时保留状态，避免一帧漏检马上制造“离开再进入”。
        """
        # 状态机时间必须单调；事件时间另用当前 UTC，保证回放仍能得到真实发生时间。
        if not math.isfinite(timestamp) or (
                self._last_timestamp is not None and timestamp < self._last_timestamp):
            raise ValueError(
                "Event timestamps must be finite and nondecreasing")
        # 过期只删除历史状态，不合成离开事件；没有看到区域外证据就不能宣称离开。
        self._states = {
            track_id: state
            for track_id, state in self._states.items()
            if timestamp - state.last_seen <= self.state_timeout_seconds
        }
        # 同一批轨迹事件共享一个 UTC 时间，便于日志和截图按批次对齐。
        occurred_at = datetime.now(
            timezone.utc).isoformat(
            timespec="milliseconds").replace(
            "+00:00",
            "Z")
        events = []
        diagnostics = []
        # 每条轨迹独立推进 inside、last_enter 和 last_seen 三个状态维度。
        self._frame += 1
        for track in tracks:
            point = bottom_center(track.detection.bbox)
            distance = cv2.pointPolygonTest(self._contour, point, True)
            inside = distance >= 0
            state = self._states.get(track.track_id)
            if state is None:
                state = _TrackState(False if self.full_frame else None, timestamp)
                self._states[track.track_id] = state
            event_type = None
            if not self.full_frame and abs(distance) <= 2:
                state.observations = 0
                reason = "near_boundary"
            elif inside == state.inside:
                state.observations = 0
                reason = state.reason_inside if inside else "outside_roi"
            else:
                if state.frame != self._frame - 1 or state.candidate != inside:
                    state.observations = 0
                state.candidate = inside
                state.observations += 1
                reason = "confirming_inside" if inside else "confirming_outside"
                if state.observations >= 2 and track.detection.confidence >= self.confirmation_confidence:
                    previous = state.inside
                    state.inside = inside
                    state.observations = 0
                    reason = "inside_observed" if inside else "outside_roi"
                    if inside and previous is False:
                        if state.last_enter is None or timestamp - state.last_enter >= self.cooldown_seconds:
                            event_type = "person_entered"
                            state.last_enter = timestamp
                            reason = "present" if self.full_frame else "entered"
                        else:
                            reason = "cooldown"
                    elif not inside and previous is True and self.emit_leave:
                        event_type = "person_left"
                        reason = "left"
                    if inside:
                        state.reason_inside = {"entered": "already_inside", "cooldown": "inside_suppressed",
                                               "present": "full_frame_present"}.get(reason, reason)
            state.frame = self._frame
            remaining = max(0., self.cooldown_seconds - (timestamp - state.last_enter)) \
                if state.last_enter is not None else 0.
            diagnostics.append({
                "track_id": track.track_id, "bbox": list(track.detection.bbox),
                "confidence": track.detection.confidence,
                "point": list(point),
                "inside": inside, "reason": reason,
                "cooldown_remaining": remaining, "roi_name": self.roi_name,
            })
            # 状态先转换成纯 Event，再由流水线决定截图、JSONL 和 MQTT 等副作用。
            if event_type is not None:
                events.append(
                    Event(
                        event_id=str(
                            uuid4()),
                        event_type=event_type,
                        occurred_at=occurred_at,
                        confidence=track.detection.confidence,
                        roi_name=self.roi_name,
                        bbox=track.detection.bbox,
                        snapshot_path=None,
                        source_name=source_name,
                        track_id=track.track_id,
                        source_time=source_time,
                    ))
            state.last_seen = timestamp
        self._last_timestamp = timestamp
        self.diagnostics = diagnostics
        return events
