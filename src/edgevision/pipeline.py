"""同步基线和有界最新帧处理流水线，共用同一套业务逻辑。

完整链路是：输入源 →（可选）容量为 1 的队列 → 方向校正 → ONNX 检测
→ 跟踪 → ROI 事件 → 截图/JSONL/MQTT；预览和指标从旁路读取结果。

``sync`` 模式让采集和处理在同一线程中顺序执行，作为不丢帧的吞吐基线；
``latest`` 模式把采集放到独立线程，队列只保留最新帧，优先降低处理结果的帧龄。
"""
import logging
import queue
import threading
import time
import cv2
from .delivery import DeliveryWorker
from .health import FrameHealth
from .trace import FrameTrace
from .events import EventEngine
from .frame_queue import LatestFrameQueue, QueueClosed
from .metrics import Metrics
from .mqtt_client import MqttPublisher
from .storage import EventStorage
from .sources import orient_image
from .tracker import CentroidIoUTracker

LOG = logging.getLogger(__name__)


class _EventOutputWorker:
    """Encode optional screenshots after the event record is durable."""

    def __init__(self, pipeline, max_pending=32):
        self.pipeline = pipeline
        self.queue = queue.Queue(maxsize=max_pending)
        self.closed = False
        self.completed = 0
        self.thread = threading.Thread(target=self._run, name="event-output", daemon=True)
        self.thread.start()

    def submit(self, event, image):
        try:
            self.queue.put_nowait((event, image, time.monotonic()))
            return True
        except queue.Full:
            return False

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            event, image, queued_at = item
            try:
                try:
                    saved = self.pipeline.storage.attach_snapshot(event, image)
                except Exception:
                    saved = False
                    LOG.exception("Snapshot write failed for %s", event.event_id)
                if saved:
                    self.pipeline.metrics.snapshot_saved += 1
                else:
                    self.pipeline.metrics.snapshot_skipped += 1
                self.pipeline.metrics.event_output.add(
                    (time.monotonic() - queued_at) * 1000)
            finally:
                self.completed += 1
                self.queue.task_done()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.queue.put(None, timeout=5)
        except queue.Full as exc:
            raise RuntimeError("Event output worker stalled with a full queue") from exc
        # Allow a long backlog to drain while completed events show forward progress.
        while self.thread.is_alive():
            previous = self.completed
            self.thread.join(timeout=5)
            if self.thread.is_alive() and self.completed == previous:
                raise RuntimeError("Event output worker made no progress during shutdown")


class Pipeline:
    """编排采集、推理、事件输出和运行指标，不拥有具体模型实现。"""

    def __init__(self, config, source, detector, preview=None):
        self.config = config
        self.source = source
        self.detector = detector
        self.preview = preview
        self.queue = LatestFrameQueue(maxsize=1)
        self.tracker = CentroidIoUTracker()
        self.storage = EventStorage(
            config.output.directory,
            config.output.max_bytes,
            config.output.retention_days,
            config.output.min_free_bytes)
        self.mqtt = MqttPublisher(**vars(config.mqtt))
        self.metrics = Metrics()
        self.stop_event = threading.Event()
        self.engine = None
        self.engine_shape = None
        self.active_roi_name = None
        self.active_roi_points = None
        self.storage.queue_delivery = config.mqtt.enabled
        self.frame_health = FrameHealth(self.mqtt.publish_health)
        if hasattr(self.source, "on_read_failure"):
            self.source.on_read_failure = self.frame_health.observe
        self.events_persisted = 0
        self.delivery = None
        self.storage_failed = 0
        self.capture_error = None
        self._trace = None
        self.trace_failed = False
        self.output_queue_dropped = 0
        self._output = None

    def stop(self):
        # 停止信号、输入源和帧队列一起关闭，确保生产者和消费者都能从阻塞点退出。
        self.stop_event.set()
        self.source.close()
        self.queue.close()

    def _process(self, frame):
        """处理一帧：先统一坐标，再检测、关联轨迹、生成并输出事件。"""
        # 方向必须先于检测和 ROI 转换，否则画面、框和区域会处在不同坐标系。
        frame.image = orient_image(
            frame.image,
            self.config.input.rotation,
            self.config.input.mirror_horizontal)
        shape = frame.image.shape
        if self.engine_shape != shape[:2]:
            # 分辨率变化会改变 ROI 像素坐标，也会让旧轨迹失去意义，因此一起重置状态。
            self.engine_shape = shape[:2]
            self.tracker = CentroidIoUTracker()
            if self.config.roi.enabled:
                polygon = [(p[0] * shape[1], p[1] * shape[0])
                           for p in self.config.roi.points]
                roi_name = self.config.roi.name
                roi_points = self.config.roi.points
            else:
                # Disabled ROI means every visible detection is eligible for
                # an entry event; keep a full-frame polygon for the existing
                # state machine and preview geometry.
                polygon = [(0., 0.), (float(shape[1]), 0.),
                           (float(shape[1]), float(shape[0])), (0., float(shape[0]))]
                roi_name = "全画面"
                roi_points = [[0., 0.], [1., 0.], [1., 1.], [0., 1.]]
            self.active_roi_name = roi_name
            self.active_roi_points = roi_points
            self.engine = EventEngine(
                roi_name,
                polygon,
                self.config.events.cooldown_seconds,
                self.config.events.emit_leave,
                full_frame=not self.config.roi.enabled,
                confirmation_confidence=self.config.events.confirmation_confidence)
        detections = self.detector.detect(frame.image)
        # 回放使用媒体时间推进状态机，实时输入使用 captured_at；Event 自己仍记录 UTC 时间。
        clock = frame.source_time if frame.source_time is not None else frame.captured_at
        tracks = self.tracker.update(detections, clock, shape)
        events = self.engine.update(
            tracks, clock, frame.source_name, frame.source_time)

        sharpness = None
        for event in events:
            queued_at = time.monotonic()
            self.metrics.events += 1
            if sharpness is None:
                gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            focused = sharpness >= self.config.input.min_sharpness
            self.metrics.focus(sharpness, focused)
            event.snapshot_note = ("仅保存事件，截图尚未写入" if focused else
                                   f"blurred frame: Laplacian={sharpness:.1f}, "
                                   f"threshold={self.config.input.min_sharpness:.1f}")
            try:
                self.storage.save(event, None)
            except Exception:
                self.storage_failed += 1
                self.metrics.snapshot_skipped += 1
                LOG.exception("Event persistence failed for %s", event.event_id)
                continue
            self.events_persisted += 1
            if self.delivery:
                self.delivery.wake.set()
            if focused:
                annotated = frame.image.copy()
                x1, y1, x2, y2 = map(int, event.bbox)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
                if not self._output.submit(event, annotated):
                    self.output_queue_dropped += 1
                    self.metrics.snapshot_skipped += 1
            else:
                self.metrics.snapshot_skipped += 1
                self.metrics.event_output.add((time.monotonic() - queued_at) * 1000)
            self.metrics.event_end_to_end.add(
                (time.monotonic() - frame.captured_at) * 1000)

        # 帧级指标即使没有事件也要更新，否则只有告警帧会被误认为处理吞吐。
        elapsed = (time.monotonic() - frame.captured_at) * 1000
        inference = self.detector.last_inference_ms
        self.metrics.processed_frames += 1
        self.metrics.inference.add(inference)
        self.metrics.end_to_end.add(elapsed)
        if frame.source_time is not None and self.source.start_time is not None:
            self.metrics.max_media_lag_ms = max(self.metrics.max_media_lag_ms, max(
                0, (time.monotonic() - self.source.start_time - frame.source_time) * 1000))
        self.metrics.health()

        # 预览和 trace 都是旁路输出，失败不应改变检测、事件和存储主链路。
        if self.preview:
            diagnostics = [{**entry, "bottom_clipped": entry["bbox"][3] >= shape[0] - 1}
                           for entry in self.engine.diagnostics]
            self.preview.update(frame,
                                detections,
                                tracks,
                                events,
                                self.engine.polygon,
                                {"processed_frames": self.metrics.processed_frames,
                                 "events": self.metrics.events,
                                 "track_diagnostics": diagnostics,
                                 "inside_count": sum(entry["inside"] for entry in diagnostics),
                                 "storage_failed": self.storage_failed,
                                 "roi_name": self.active_roi_name,
                                 "roi_enabled": self.config.roi.enabled,
                                 "roi_points": self.active_roi_points,
                                 "queue_dropped_frames": self.queue.dropped_count,
                                 "queue_drop_rate": self.queue.dropped_count / max(1, self.metrics.capture_frames),
                                 "frame_age_p95_ms": self.metrics.end_to_end.percentile(.95),
                                 "focus_rejected": self.metrics.focus_rejected,
                                 "snapshot_saved": self.metrics.snapshot_saved,
                                 "snapshot_skipped": self.metrics.snapshot_skipped,
                                 "fps": self.metrics.processed_frames / max(.001,
                                                                            time.monotonic() - self.metrics.started)})
        if self._trace:
            try:
                self._trace.writerow({"seq": frame.seq,
                                       "source_time": frame.source_time,
                                       "inference_ms": inference,
                                       "software_frame_age_ms": elapsed,
                                       "detections": len(detections),
                                       "events": len(events),
                                       "rss_bytes": self.metrics.process.memory_info().rss,
                                       "queue_dropped": self.queue.dropped_count})
            except (OSError, ValueError):
                self.trace_failed = True
                LOG.exception("Disabling diagnostic trace after a write failure")
                try:
                    self._trace.close()
                except OSError:
                    LOG.exception("Could not flush diagnostic trace")
                self._trace = None

    def run(
            self,
            mode="latest",
            max_frames=None,
            duration=None,
            trace_path=None):
        """运行同步或采集/消费分离模式，并返回一次运行的统计字典。

        ``sync`` 用于建立没有队列丢帧的基线；``latest`` 用采集线程和
        容量为 1 的队列追求实时性。单帧异常只计数并继续处理后续帧。
        """
        # run 只负责线程/资源编排；单帧业务细节集中在 _process，保持两种模式行为一致。
        if mode not in ("sync", "latest"):
            raise ValueError("mode must be sync or latest")
        self.metrics = Metrics()
        deadline = time.monotonic() + duration if duration else float("inf")
        timer = None
        if duration:
            timer = threading.Timer(duration, self.stop)
            timer.daemon = True
            timer.start()

        def limited():
            # 把帧数、时长和 stop 条件统一放在输入迭代器上，两个模式共享同一套边界。
            iterator = iter(self.source)
            while True:
                if self.stop_event.is_set() or time.monotonic() >= deadline:
                    break
                if max_frames is not None and self.metrics.capture_frames >= max_frames:
                    break
                try:
                    frame = next(iterator)
                except StopIteration:
                    break
                if self.stop_event.is_set():
                    break
                self.metrics.capture_frames += 1
                yield frame

        def consume(frame):
            # 单帧异常只记录并继续，避免一张坏帧结束整段回放或实时服务。
            try:
                self._process(frame)
                self.frame_health.observe(captured_at=frame.captured_at)
            except Exception:
                self.frame_health.observe("frame_processing")
                self.metrics.errors += 1
                LOG.exception("Frame %s processing failed", frame.seq)

        def capture():
            # 采集线程只负责把帧交给有界队列；队列关闭后不再尝试写入。
            try:
                for frame in limited():
                    try:
                        self.queue.put(frame)
                    except QueueClosed:
                        break
            except Exception as exc:
                self.capture_error = exc
                LOG.exception("Capture failed")
            finally:
                self.queue.close()
                self.source.close()
        thread = None
        try:
            if trace_path:
                try:
                    self._trace = FrameTrace(trace_path, self.storage.root)
                except OSError:
                    self.trace_failed = True
                    LOG.exception("Could not open diagnostic trace")
            self.mqtt.connect()
            if self.config.mqtt.enabled:
                self.delivery = DeliveryWorker(self.storage, self.mqtt, self.frame_health)
            self._output = _EventOutputWorker(self)
            if mode == "sync":
                # 基线模式不创建队列，便于比较没有丢帧时的处理吞吐。
                for frame in limited():
                    consume(frame)
            else:
                # latest 模式中采集和消费并行，消费者拿到的可能是跳过旧帧后的最新帧。
                thread = threading.Thread(
                    target=capture, name="capture", daemon=True)
                thread.start()
                while not self.stop_event.is_set():
                    if time.monotonic() >= deadline:
                        break
                    try:
                        frame = self.queue.get(timeout=.25)
                    except queue.Empty:
                        continue
                    except QueueClosed:
                        break
                    consume(frame)
        finally:
            # 无论正常结束、超时还是异常，都按同一顺序停止计时器、输入、线程、MQTT 和 trace。
            self.metrics.finished_at = time.monotonic()
            if timer:
                timer.cancel()
            self.stop()
            if thread:
                thread.join(timeout=7)
                if thread.is_alive():
                    raise RuntimeError("Capture thread failed to stop")
            try:
                if self._output is not None:
                    self._output.close()
            finally:
                if self.delivery:
                    self.delivery.close()
                self.mqtt.publish_health({**self.frame_health.status(), "state": "stopped"})
                self.mqtt.close()
                if self._trace:
                    self._trace.close()
        if self.capture_error:
            raise RuntimeError(
                f"Input failed: {self.capture_error}") from self.capture_error
        result = self.metrics.summary()
        # 在基础指标上补充队列、重连、存储和 MQTT 结果，方便一次运行的 JSON 直接验收。
        mqtt_status = self.mqtt.status()
        try:
            backlog = len(self.storage.pending_events()) if self.config.mqtt.enabled else 0
        except (OSError, ValueError, RuntimeError):
            backlog = None
            LOG.exception("Could not read MQTT backlog from event storage")
        result.update({"mode": mode,
                       "input_rotation": self.config.input.rotation,
                       "input_mirror_horizontal": self.config.input.mirror_horizontal,
                       "queue_dropped_frames": self.queue.dropped_count,
                       "queue_drop_rate": self.queue.dropped_count / max(1,
                                                                         self.metrics.capture_frames),
                       "max_queue_size": self.queue.high_watermark,
                       "app_queue_wait_p95_ms": self.queue.wait_p95_ms,
                       "max_queue_wait_ms": self.queue.max_frame_age * 1000,
                       "camera_reconnects": getattr(self.source,
                                                    "reconnects",
                                                    0),
                       "camera_driver_dropped_frames": getattr(self.source,
                                                               "driver_dropped_frames",
                                                               0),
                       "camera_ipc_skipped_frames": getattr(self.source, "driver_dropped_frames", 0),
                       "storage_failed": self.storage_failed,
                       "trace_failed": self.trace_failed,
                       "output_queue_dropped": self.output_queue_dropped,
                       "events_persisted": self.events_persisted,
                       "events_dropped": self.storage_failed,
                       "frame_health": self.frame_health.status(),
                       "mqtt_outbox_pending": backlog,
                       "mqtt_published": mqtt_status["accepted"],
                       "mqtt_failed": mqtt_status["failed"],
                       "mqtt_acknowledged": mqtt_status["acknowledged"],
                       "mqtt_pending": mqtt_status["pending"]})
        return result
