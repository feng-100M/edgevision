"""仅监听回环地址的摄像头预览，帧和状态都保持在有界内存中。

预览是旁路功能：它接收流水线已经校正过的帧和轨迹，独立线程限速绘制
和 JPEG 编码，不能阻塞检测线程；浏览器只访问 ``127.0.0.1``。

HTTP 线程只读取最近状态或最近 JPEG，渲染线程只消费一份待绘制帧；
两者都通过同一把 Condition 协调，预览变慢时最多丢掉待绘制帧，不影响检测主循环。
"""
from collections import deque
from importlib.resources import files
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import socket
import threading
import time
import cv2
import numpy as np
import re
from urllib.parse import unquote
from datetime import datetime, timezone
from .geometry import bottom_center, point_in_polygon
from .storage import StorageError

PAGE = files("edgevision").joinpath("dashboard.html").read_text(encoding="utf-8")
SCRIPT = files("edgevision").joinpath("dashboard.js").read_text(encoding="utf-8")


class PreviewServer:
    """提供状态 JSON、单帧 JPEG 和 MJPEG 流的本地预览服务。"""

    def __init__(self, port=8765, on_stop=None, event_store=None, mqtt_status=None):
        self.on_stop = on_stop
        self.event_store = event_store
        self.mqtt_status = mqtt_status
        self._lock = threading.Condition()
        self._jpeg = None
        self._status = {}
        self._events = deque(maxlen=12)
        self._jpeg_seq = None
        self._pending = None
        self._closed = False
        self._rendered = 0
        self._render_started = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                # 访问日志由预览自身状态页提供，避免污染检测服务日志。
                pass

            def send(self, code, body, content_type):
                # 所有短响应都在这里统一写头，并处理浏览器提前断开。
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                # GET 只提供页面、状态和最近一帧，不在 HTTP 线程执行绘制或推理。
                path = self.path.split("?", 1)[0]
                if path == "/":
                    self.send(
                        200,
                        PAGE.encode("utf8"),
                        "text/html; charset=utf-8")
                elif path == "/dashboard.js":
                    self.send(200, SCRIPT.encode("utf8"), "text/javascript; charset=utf-8")
                elif path == "/status":
                    with owner._lock:
                        status = {**owner._status,
                                  "preview_frames": owner._rendered,
                                  "preview_fps": owner._rendered / max(.001,
                                                                       time.monotonic() - owner._render_started) if owner._render_started else 0.}
                    status["server_time"] = datetime.now(timezone.utc).isoformat()
                    status["display_timezone"] = "Asia/Shanghai"
                    status["mqtt"] = owner.mqtt_status() if owner.mqtt_status else {"state": "unavailable"}
                    data = json.dumps(status, ensure_ascii=False).encode("utf8")
                    self.send(200, data, "application/json; charset=utf-8")
                elif path == "/events":
                    try:
                        events = owner.event_store.recent_events() if owner.event_store else []
                        body = {"events": events}
                        self.send(200, json.dumps(body, ensure_ascii=False).encode("utf8"),
                                  "application/json; charset=utf-8")
                    except StorageError:
                        logging.exception("Event history read failed")
                        self.send(503, json.dumps({"error": "事件记录暂时无法读取，请检查存储日志"},
                                                  ensure_ascii=False).encode("utf8"),
                                  "application/json; charset=utf-8")
                elif path.startswith("/snapshots/"):
                    event_id = unquote(path[len("/snapshots/"):])
                    data = None
                    if owner.event_store and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", event_id):
                        try:
                            data = owner.event_store.snapshot(event_id)
                        except StorageError:
                            logging.exception("Event snapshot read failed")
                    self.send(200 if data else 404, data or b"Not found",
                              "image/jpeg" if data else "text/plain")
                elif path == "/stream.mjpg":
                    # MJPEG 客户端按序列号等待新 JPEG，避免重复发送同一帧。
                    self.stream()
                elif path == "/frame.jpg":
                    with owner._lock:
                        data = owner._jpeg
                    self.send(
                        200 if data else 503,
                        data or b"No frame yet",
                        "image/jpeg" if data else "text/plain")
                else:
                    self.send(404, b"Not found", "text/plain")

            def stream(self):
                # 回环地址上的长连接只发送最新渲染结果；客户端断开时立即退出。
                self.connection.settimeout(2)
                self.connection.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.connection.setsockopt(
                    socket.SOL_SOCKET, socket.SO_SNDBUF, 32768)
                try:
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    previous = None
                    while True:
                        with owner._lock:
                            owner._lock.wait_for(
                                lambda: owner._closed or owner._jpeg_seq != previous, timeout=1)
                            if owner._closed:
                                return
                            if owner._jpeg_seq == previous:
                                continue
                            previous = owner._jpeg_seq
                            data = owner._jpeg
                        header = (
                            f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\n"
                            f"X-Sequence: {previous}\r\n\r\n").encode()
                        self.wfile.write(header + data + b"\r\n")
                        self.wfile.flush()
                except (OSError, TimeoutError):
                    return

            def do_POST(self):
                # 停止请求只调用流水线的停止回调，资源清理由外层 finally 完成。
                if self.path == "/stop":
                    self.send(200, b"Stopping", "text/plain")
                    if owner.on_stop:
                        owner.on_stop()
                else:
                    self.send(404, b"Not found", "text/plain")
        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(
                poll_interval=.1), name="preview", daemon=True)
        self._thread.start()
        self._renderer = threading.Thread(
            target=self._render_loop,
            name="preview-render",
            daemon=True)
        self._renderer.start()

    def update(self, frame, detections, tracks, events, polygon, metrics):
        """发布最新状态和待绘制帧；旧的待绘制帧可以被新帧覆盖。"""
        with self._lock:
            # 状态和事件立即可读；待绘制帧只保留一份，保证渲染线程不会追赶历史积压。
            for event in events:
                self._events.append(event.to_dict())
            self._status = {"seq": frame.seq, "detections": len(detections),
                            "frame_width": frame.image.shape[1],
                            "frame_height": frame.image.shape[0],
                            **metrics, "recent_events": list(self._events)}
            if not self._closed:
                self._pending = (frame, list(tracks), list(polygon))
                self._lock.notify_all()

    def _render_loop(self):
        # 渲染上限约 30 FPS；检测线程只负责发布 pending，不等待 JPEG 编码完成。
        last_render = 0.
        while True:
            with self._lock:
                self._lock.wait_for(
                    lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                delay = 1 / 30 - (time.monotonic() - last_render)
                if delay > 0:
                    self._lock.wait(timeout=delay)
                    continue
                frame, tracks, polygon = self._pending
                self._pending = None
            last_render = time.monotonic()
            try:
                # 绘制失败只影响这一帧预览，不能反向中断检测线程。
                data = self._render(frame, tracks, polygon)
            except Exception:
                logging.exception("Preview frame encoding failed")
                continue
            if data:
                with self._lock:
                    if self._render_started is None:
                        self._render_started = last_render
                    self._jpeg = data
                    self._jpeg_seq = frame.seq
                    self._rendered += 1
                    self._lock.notify_all()

    def _render(self, frame, tracks, polygon):
        # 先叠加 ROI，再绘制每条轨迹的框、脚部中心点和 ID，最后缩放并编码 JPEG。
        picture = frame.image.copy()
        points = np.array(polygon, np.int32)
        overlay = picture.copy()
        cv2.fillPoly(overlay, [points], (220, 100, 20))
        picture = cv2.addWeighted(picture, .88, overlay, .12, 0)
        cv2.polylines(picture, [points], True, (255, 120, 30), 2)
        for track in tracks:
            detection = track.detection
            point = bottom_center(detection.bbox)
            inside = point_in_polygon(point, polygon)
            color = (0, 90, 255) if inside else (70, 220, 90)
            x1, y1, x2, y2 = map(int, detection.bbox)
            cv2.rectangle(picture, (x1, y1), (x2, y2), color, 2)
            cv2.circle(picture, tuple(map(int, point)), 5, color, -1)
            cv2.putText(
                picture, f"person #{track.track_id} {detection.confidence:.2f}", (x1, max(
                    18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1, cv2.LINE_AA)
        if picture.shape[1] > 480:
            height = max(1, round(picture.shape[0] * 480 / picture.shape[1]))
            picture = cv2.resize(
                picture, (480, height), interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(
            ".jpg", picture, [
                cv2.IMWRITE_JPEG_QUALITY, 60])
        return buffer.tobytes() if ok else None

    def close(self):
        """停止 HTTP 服务和渲染线程，并唤醒所有等待者。"""
        with self._lock:
            # 先设置关闭标记并唤醒 Condition，再关闭 HTTP 服务，避免等待线程永久挂起。
            self._closed = True
            self._pending = None
            self._lock.notify_all()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        self._renderer.join(timeout=2)
