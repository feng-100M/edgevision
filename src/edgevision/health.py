"""Capture/processing health shared by the producer, detector and status API."""
from datetime import datetime, timezone
from threading import Lock
import time


class FrameHealth:
    def __init__(self, notify):
        self._lock = Lock()
        self.notify = notify
        self._camera_failed_at = float("-inf")
        self._status = {"state": "starting", "last_success_at": None,
                        "consecutive_failures": 0, "last_failure_at": None,
                        "last_recovery_at": None, "reason": None}

    def status(self):
        with self._lock:
            return self._status.copy()

    def observe(self, failure=None, captured_at=None):
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            status = self._status
            previous = status["state"]
            if failure == "camera_read":
                self._camera_failed_at = time.monotonic()
            if captured_at is not None and captured_at < self._camera_failed_at:
                status["last_success_at"] = now
                return
            if failure:
                status["state"] = "unavailable"
                status["reason"] = failure
                status["last_failure_at"] = now
                status["consecutive_failures"] += 1
            else:
                status["state"] = "recovered" if previous == "unavailable" else "healthy"
                if previous == "unavailable":
                    status["last_recovery_at"] = now
                status.update(last_success_at=now, consecutive_failures=0, reason=None)
            changed = previous != status["state"]
            if changed:
                self.notify(status.copy())

    def heartbeat(self):
        with self._lock:
            self.notify(self._status.copy())
