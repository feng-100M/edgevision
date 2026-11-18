"""有界延迟直方图，以及进程和树莓派健康指标。

指标同时区分采集 FPS、处理 FPS、模型计算耗时、软件帧龄、RSS、温度、
降频和 swap，避免把“模型快”误解成“端到端实时”。

指标采集是旁路观察，不参与检测决策。所有运行时延迟使用单调时钟，
回放媒体时间只用于计算相对现实的 lag，不混入端到端软件计时。
"""
from collections import Counter
from pathlib import Path
import math
import subprocess
import time
import psutil


class Histogram:
    """把毫秒值按整数桶累计，用固定内存近似计算分位数。"""

    def __init__(self):
        self.counts = Counter()
        self.count = 0
        self.maximum = 0.
        self.clipped = 0
        self.total_ms = 0.

    def add(self, ms):
        """加入样本并更新最大值；超长样本会被限制在直方图上限。"""
        # 固定桶数让长时间运行的内存占用稳定；clipped 单独记录超过上限的样本数。
        ms = max(0., float(ms))
        self.maximum = max(self.maximum, ms)
        self.total_ms += ms
        self.clipped += int(ms > 60000)
        self.counts[min(60000, round(ms))] += 1
        self.count += 1

    def percentile(self, fraction):
        """返回近似分位数，没有样本时返回 ``None``。"""
        if not self.count:
            return None
        threshold = math.ceil(self.count * fraction)
        seen = 0
        for bucket, count in sorted(self.counts.items()):
            seen += count
            if seen >= threshold:
                return bucket


class Metrics:
    """收集一次运行的吞吐、延迟、资源和板级状态。"""

    def __init__(self):
        self.started = time.monotonic()
        self.process = psutil.Process()
        self.process.cpu_percent(None)
        self.capture_frames = 0
        self.processed_frames = 0
        self.errors = 0
        self.events = 0
        self.inference = Histogram()
        self.end_to_end = Histogram()
        self.event_end_to_end = Histogram()
        self.event_output = Histogram()
        self.peak_rss_bytes = 0
        self.peak_cpu_percent = 0.
        self.temperature_c = None
        self.peak_temperature_c = None
        self.throttled = None
        self.swap_initial = psutil.swap_memory()
        self.last_health = 0.
        self.max_media_lag_ms = 0.
        self.finished_at = None
        self.focus_samples = 0
        self.focus_total = 0.
        self.focus_min = None
        self.focus_max = None
        self.focus_rejected = 0
        self.snapshot_saved = 0
        self.snapshot_skipped = 0

    def focus(self, sharpness, accepted):
        self.focus_samples += 1
        self.focus_total += float(sharpness)
        self.focus_min = float(sharpness) if self.focus_min is None else min(self.focus_min, float(sharpness))
        self.focus_max = float(sharpness) if self.focus_max is None else max(self.focus_max, float(sharpness))
        if not accepted:
            self.focus_rejected += 1

    def health(self):
        """低频读取 RSS、CPU、温度和降频标志，避免健康检查拖慢推理。"""
        # RSS 每次都更新，温度、CPU 和 vcgencmd 每秒最多读取一次，减少系统调用开销。
        self.peak_rss_bytes = max(
            self.peak_rss_bytes,
            self.process.memory_info().rss)
        if time.monotonic() - self.last_health < 1.:
            return
        self.last_health = time.monotonic()
        self.peak_cpu_percent = max(
            self.peak_cpu_percent,
            self.process.cpu_percent(None))
        try:
            self.temperature_c = float(
                Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
            self.peak_temperature_c = max(
                self.peak_temperature_c or 0, self.temperature_c)
        except (OSError, ValueError):
            pass
        try:
            p = subprocess.run(["vcgencmd", "get_throttled"],
                               capture_output=True, text=True, timeout=.5)
            if p.returncode == 0:
                self.throttled = p.stdout.strip().split("=")[-1]
        except (OSError, subprocess.TimeoutExpired):
            pass

    def summary(self):
        """生成 JSON 可序列化的最终统计，并计算本次 swap 增量。"""
        # 汇总时补做一次健康检查，并以运行开始/结束的单调时间计算吞吐率。
        self.health()
        duration = max(.001,
                       (self.finished_at or time.monotonic()) - self.started)
        swap = psutil.swap_memory()
        result = {"duration_seconds": duration, "capture_frames": self.capture_frames,
                "processed_frames": self.processed_frames, "capture_fps": self.capture_frames / duration,
                "inference_fps": self.processed_frames / duration, "end_to_end_processing_fps": self.processed_frames / duration,
                "model_compute_fps": self.processed_frames / max(.001, self.inference.total_ms / 1000),
                "inference_fps_definition": "completed inferences per processing wall time; source pacing included",
                "errors": self.errors, "events": self.events,
                "inference_p50_ms": self.inference.percentile(.5), "inference_p95_ms": self.inference.percentile(.95),
                "end_to_end_p95_ms": self.end_to_end.percentile(.95),
                "event_end_to_end_p95_ms": self.event_end_to_end.percentile(.95),
                "event_output_p95_ms": self.event_output.percentile(.95),
                "max_software_frame_age_ms": self.end_to_end.maximum,
                "max_media_lag_ms": self.max_media_lag_ms,
                "peak_rss_bytes": self.peak_rss_bytes, "peak_process_cpu_percent": self.peak_cpu_percent,
                "temperature_c": self.temperature_c, "peak_temperature_c": self.peak_temperature_c, "throttled": self.throttled,
                "swap_in_bytes": max(0, swap.sin - self.swap_initial.sin),
                "swap_out_bytes": max(0, swap.sout - self.swap_initial.sout),
                "histogram_resolution_ms": 1, "histogram_limit_ms": 60000,
                "latency_clipped_samples": self.end_to_end.clipped,
                "frame_age_definition": "software_read_completion_to_processing_end; sensor/USB buffering excluded"}
        result = {**result,
                  "focus_score_mean": self.focus_total / self.focus_samples if self.focus_samples else None,
                  "focus_score_min": self.focus_min,
                  "focus_score_max": self.focus_max,
                  "focus_rejected": self.focus_rejected,
                  "snapshot_saved": self.snapshot_saved,
                  "snapshot_skipped": self.snapshot_skipped}
        return result
