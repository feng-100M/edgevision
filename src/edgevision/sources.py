"""视频文件和可重启的 USB 摄像头输入，并隔离可能卡住的驱动调用。

文件回放适合先验证检测和事件逻辑；UVC 输入则把 ``VideoCapture`` 放在
子进程中，主进程可以在读帧超时时结束这个子进程并重新连接，避免驱动
阻塞把整条告警流水线锁死。

两种输入都产出同一个 ``Frame`` 契约：视频源提供媒体时间，UVC 源只提供本机
单调时间。这样回放可以按文件节奏计算延迟，实时摄像头则不会伪造不存在的媒体位置。
"""
from pathlib import Path
import logging
import multiprocessing as mp
import queue
import threading
import time
import cv2
from .types import Frame

LOG = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """输入源无法打开或无法提供有效帧时抛出的异常。"""
    pass


def rotate_image(image, degrees):
    """在推理和叠加绘制前按顺时针方向校正摄像头画面。"""
    if degrees == 0:
        return image
    codes = {
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    if degrees not in codes:
        raise ValueError("rotation must be 0, 90, 180 or 270")
    return cv2.rotate(image, codes[degrees])


def orient_image(image, rotation=0, mirror_horizontal=False):
    # 方向校正放在检测前，保证框、ROI、预览和截图使用同一套坐标。
    image = rotate_image(image, rotation)
    return cv2.flip(image, 1) if mirror_horizontal else image


class VideoFileSource:
    """把视频文件暴露成带媒体时间的 ``Frame`` 迭代器。"""

    def __init__(self, path, realtime=True, loop=False):
        self.path = Path(path)
        self.realtime = realtime
        self.loop = loop
        self.closed = False
        self.stop = threading.Event()
        self.start_time = None

    def __iter__(self):
        # 每次迭代都重新打开文件，使 loop、stop 和异常结束后的生命周期清晰可控。
        self.closed = False
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            cap.release()
            self.closed = True
            raise SourceError(f"Cannot open video: {self.path}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            cap.release()
            raise SourceError("Video has no valid FPS metadata")
        self.fps = fps
        self.start_time = time.monotonic()
        seq = 0
        try:
            while not self.stop.is_set():
                ok, image = cap.read()
                if not ok:
                    if self.loop and seq > 0:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, image = cap.read()
                    if not ok:
                        break
                # 媒体时间来自帧序号和文件 FPS，不使用读取速度替代视频本身的时间轴。
                media_time = seq / fps
                if self.realtime:
                    if self.stop.wait(
                            max(0, self.start_time + media_time - time.monotonic())):
                        break
                # captured_at 测软件端到端延迟，不代表摄像头传感器曝光时刻。
                yield Frame(seq, time.monotonic(), image, str(self.path), media_time)
                seq += 1
        finally:
            cap.release()
            self.closed = True

    def close(self):
        self.stop.set()


def _capture_camera(device, width, height, fps, focus_warmup_frames, out, stop):
    # 摄像头读取放在独立子进程，驱动阻塞时主进程仍能结束并重启它。
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # 两个驱动缓冲允许采集和读取重叠；应用层队列仍保持容量为 1，避免无限积压。
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        # Let UVC autofocus settle before exposing frames to inference, then
        # lock the current focus when the driver supports these controls.
        try:
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            for _ in range(max(0, focus_warmup_frames)):
                if stop.is_set():
                    return
                ok, _ = cap.read()
                if not ok:
                    return
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        except (AttributeError, cv2.error):
            pass
        seq = 0
        while not stop.is_set():
            ok, image = cap.read()
            if not ok:
                return
            item = (seq, time.monotonic(), image)
            try:
                out.put_nowait(item)
            except queue.Full:
                try:
                    out.get_nowait()
                except queue.Empty:
                    pass
                try:
                    out.put_nowait(item)
                except queue.Full:
                    pass
            seq += 1
    finally:
        cap.release()


class UvcCameraSource:
    """可重连的 UVC 输入；超时时只终止摄像头子进程。

    采集子进程使用容量为 1 的进程队列，驱动层和应用层都不会无限积压旧帧。
    """

    def __init__(
            self,
            device="/dev/video0",
            width=640,
            height=480,
            fps=15,
            retry_seconds=1.,
            focus_warmup_frames=30,
            timeout_seconds=5.):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.retry_seconds = retry_seconds
        self.focus_warmup_frames = focus_warmup_frames
        self.timeout_seconds = timeout_seconds
        self.stop = threading.Event()
        self.reconnects = 0
        self.closed = True
        self.start_time = None
        self._process = None
        self.driver_dropped_frames = 0
        self.on_read_failure = None

    def __iter__(self):
        # 每轮创建新的子进程和进程队列；一轮超时或退出后，下一轮负责重连。
        self.closed = False
        seq = 0
        self.start_time = time.monotonic()
        ctx = mp.get_context("spawn")
        try:
            while not self.stop.is_set():
                out = ctx.Queue(maxsize=1)
                child_stop = ctx.Event()
                process = ctx.Process(
                    target=_capture_camera,
                    args=(
                        self.device,
                        self.width,
                        self.height,
                        self.fps,
                        self.focus_warmup_frames,
                        out,
                        child_stop),
                    daemon=True)
                self._process = process
                try:
                    process.start()
                    last_camera_seq = -1
                    last_frame_at = time.monotonic()
                    while not self.stop.is_set():
                        try:
                            camera_seq, captured_at, image = out.get(
                                timeout=min(.25, self.timeout_seconds))
                        except queue.Empty:
                            if not process.is_alive() or time.monotonic() - \
                                    last_frame_at >= self.timeout_seconds:
                                break
                            continue
                        # 用驱动序号差统计子进程内部已经丢掉的帧，再向上层交付当前最新帧。
                        last_frame_at = time.monotonic()
                        self.driver_dropped_frames += max(0,
                                                          camera_seq - last_camera_seq - 1)
                        last_camera_seq = camera_seq
                        yield Frame(seq, captured_at, image, self.device, None)
                        seq += 1
                finally:
                    child_stop.set()
                    if process.pid is not None:
                        process.join(timeout=.5)
                    if process.pid is not None and process.is_alive():
                        process.terminate()
                        process.join(timeout=1)
                    out.close()
                    out.cancel_join_thread()
                    self._process = None
                # 只有不是主动停止才算一次重连；主动 close 不应增加故障计数。
                if not self.stop.is_set():
                    self.reconnects += 1
                    if self.on_read_failure:
                        self.on_read_failure("camera_read")
                    LOG.warning(
                        "Camera %s unavailable; retry %d",
                        self.device,
                        self.reconnects)
                    self.stop.wait(self.retry_seconds)
        finally:
            self.closed = True

    def close(self):
        self.stop.set()
