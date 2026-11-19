import time
from types import SimpleNamespace

from edgevision.delivery import DeliveryWorker
from edgevision.health import FrameHealth
from edgevision.mqtt_client import MqttPublisher
from edgevision.storage import EventStorage
from test_storage import event


def test_restart_replays_only_pending_ids_without_new_frames(tmp_path, monkeypatch):
    store = EventStorage(tmp_path, min_free_bytes=0)
    store.queue_delivery = True
    store.save(event("confirmed"), None)
    store.save(event("lost-link"), None)
    store.acknowledge({"confirmed"})
    reopened = EventStorage(tmp_path, min_free_bytes=0)
    publisher = MqttPublisher()
    connected = False
    sent = []
    monkeypatch.setattr(publisher.client, "is_connected", lambda: connected)

    def send(topic, body, qos, retain):
        import json
        if topic == publisher.topic:
            sent.append(json.loads(body)["event_id"])
            publisher.client.on_publish(publisher.client, None, 1, None, None)
        return SimpleNamespace(rc=0, mid=1)

    monkeypatch.setattr(publisher.client, "publish", send)
    worker = DeliveryWorker(reopened, publisher, FrameHealth(publisher.publish_health))
    try:
        connected = True
        worker.wake.set()
        deadline = time.monotonic() + 3
        while reopened.pending_events() and time.monotonic() < deadline:
            time.sleep(.01)
        assert not reopened.pending_events()
        assert sent == ["lost-link"]
        assert publisher.status()["acknowledged"] == 1
    finally:
        worker.close()
        publisher.close()
