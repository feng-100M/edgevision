"""有界的帧交接结构，优先保证新鲜度而不是让积压无限增长。

采集速度高于推理速度时，容量为 1 的队列会丢掉旧帧，只保留最近一帧。
这会牺牲部分吞吐量，却能避免告警处理越来越落后于现实时间。

队列是采集线程和推理线程之间的唯一缓冲边界：生产者只负责发布最新帧，
消费者负责等待、取帧和记录帧龄。关闭时先唤醒等待者，再让已经入队的帧自然排空。
"""

from __future__ import annotations

from collections import deque
import math
from queue import Empty
from threading import Condition
import time

from .types import Frame
from .metrics import Histogram


class QueueClosed(RuntimeError):
    """生产者已经关闭，且队列中没有可继续消费的帧。"""


class LatestFrameQueue:
    """线程安全的最新帧队列；生产者从不因消费者变慢而阻塞。"""

    def __init__(self, maxsize: int = 1) -> None:
        if not isinstance(maxsize, int) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self.maxsize = maxsize
        self._frames: deque[tuple[Frame, float]] = deque()
        self._condition = Condition()
        self._closed = False
        self._dropped_count = 0
        self._max_frame_age = 0.0
        self._queue_wait = Histogram()
        self.high_watermark = 0

    @property
    def wait_p95_ms(self) -> int | None:
        with self._condition:
            return self._queue_wait.percentile(.95)

    @property
    def dropped_count(self) -> int:
        with self._condition:
            return self._dropped_count

    @property
    def max_frame_age(self) -> float:
        """返回观测到的最大采集到取出帧龄（单调时钟秒数）。"""
        with self._condition:
            return self._max_frame_age

    def qsize(self) -> int:
        with self._condition:
            return len(self._frames)

    def put(self, frame: Frame) -> None:
        """不等待容量；队列满时丢弃最旧帧。"""
        with self._condition:
            if self._closed:
                raise QueueClosed("Cannot put a frame into a closed queue")

            # 队列满时丢掉最旧帧而不是阻塞采集，让处理结果尽量接近当前现实时间。
            if len(self._frames) == self.maxsize:
                self._frames.popleft()
                self._dropped_count += 1
            self._frames.append((frame, time.monotonic()))
            self.high_watermark = max(self.high_watermark, len(self._frames))
            self._condition.notify()

    def get(self, timeout: float | None = None) -> Frame:
        """取出缓冲帧（容量为 1 时就是最新帧），并记录帧龄。"""
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._frames:
                # 空队列可能只是暂时没有新帧，也可能已经关闭；两者必须用不同异常区分。
                if self._closed:
                    raise QueueClosed("Frame queue is closed and drained")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise Empty
                self._condition.wait(remaining)
            # 只在真正交给消费者时计算帧龄，这个值反映等待和推理开始前的积压程度。
            frame, enqueued_at = self._frames.popleft()
            now = time.monotonic()
            self._queue_wait.add((now - enqueued_at) * 1000)
            self._max_frame_age = max(self._max_frame_age, now - frame.captured_at)
            return frame

    def close(self) -> None:
        """唤醒所有消费者，并保留已经缓冲的帧供其排空。"""
        with self._condition:
            # 关闭是幂等的；保留缓冲帧让消费者可以先处理已经采集到的最后一帧。
            self._closed = True
            self._condition.notify_all()
