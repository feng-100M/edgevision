"""Replay durable pending rows and commit real QoS 1 broker receipts."""
import logging
import threading
import time


LOG = logging.getLogger(__name__)


class DeliveryWorker:
    def __init__(self, store, publisher, health):
        self.store = store
        self.publisher = publisher
        self.health = health
        self.inflight = set()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="mqtt-outbox", daemon=True)
        self.thread.start()

    def _deliver(self):
        status = self.publisher.status()
        states = status["event_status"]
        confirmed = {key for key in self.inflight if states.get(key, {}).get("state") == "acknowledged"}
        if confirmed:
            self.store.acknowledge(confirmed)
            self.inflight.difference_update(confirmed)
        self.inflight.difference_update(key for key in tuple(self.inflight)
                                       if states.get(key, {}).get("state") == "failed")
        if status["state"] != "connected":
            return False
        pending = self.store.pending_events()
        for row in pending:
            if len(self.inflight) >= 16:
                break
            key = row["event_id"]
            if key not in self.inflight:
                payload = dict(row)
                payload.pop("delivery_state")
                if not self.publisher.publish(payload).ok:
                    break
                self.inflight.add(key)
        return bool(pending)

    def _run(self):
        heartbeat_at = 0.
        while True:
            self.wake.clear()
            try:
                pending = self._deliver()
                if time.monotonic() >= heartbeat_at:
                    self.health.heartbeat()
                    heartbeat_at = time.monotonic() + 5
            except Exception:
                LOG.exception("Could not advance durable MQTT delivery")
                pending = False
            if self.stop.is_set() and (not pending or time.monotonic() >= self.deadline):
                return
            self.wake.wait(.1 if self.inflight else .5)

    def close(self):
        self.deadline = time.monotonic() + 1
        self.stop.set()
        self.wake.set()
        self.thread.join()
