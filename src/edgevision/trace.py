"""Bounded per-frame diagnostics. Each CSV segment has its own header."""
import csv
import io
from pathlib import Path


class FrameTrace:
    MAX_BYTES = 4 * 1024 * 1024
    FIELDS = ("seq", "source_time", "inference_ms", "software_frame_age_ms",
              "detections", "events", "rss_bytes", "queue_dropped")

    def __init__(self, path, evidence_root):
        self.path = Path(path).resolve()
        self.backup = self.path.with_name(self.path.name + ".1")
        if self.path.is_relative_to(Path(evidence_root).resolve()):
            raise ValueError("Trace path must be outside event storage")
        if self.backup.is_symlink():
            raise ValueError("Unsafe trace backup path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.header = self._encode(self.FIELDS)
        self.stream = self._open()

    @staticmethod
    def _encode(values):
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerow(values)
        return buffer.getvalue().encode("utf8")

    def _open(self):
        stream = self.path.open("wb")
        stream.write(self.header)
        return stream

    def writerow(self, row):
        line = self._encode([row[key] for key in self.FIELDS])
        if len(line) + len(self.header) > self.MAX_BYTES:
            raise ValueError("Frame trace row exceeds segment size")
        if self.stream.tell() + len(line) > self.MAX_BYTES:
            self.stream.close()
            self.path.replace(self.backup)
            self.stream = self._open()
        self.stream.write(line)
        self.stream.flush()

    def close(self):
        self.stream.close()
