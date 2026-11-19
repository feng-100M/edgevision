import socket
import time
from dataclasses import asdict
import pytest

def test_broker_unavailable_never_stalls_event_processing():
    from edgevision.mqtt_client import MqttPublisher
    s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1]
    # Keep bound but not listening, giving a deterministic refused port.
    publisher=MqttPublisher(port=port)
    started=time.monotonic()
    publisher.connect()
    result=publisher.publish({"event":"test"})
    publisher.close()
    s.close()
    assert not result.ok
    assert time.monotonic()-started < 2.5

def test_disabled_publisher_is_explicitly_skipped():
    from edgevision.mqtt_client import MqttPublisher
    publisher=MqttPublisher(enabled=False)
    assert publisher.publish({"event":"test"}).error == "disabled"
    publisher.close()

def test_connected_broker_without_ack_cannot_grow_outgoing_queue():
    import threading
    from edgevision.mqtt_client import MqttPublisher
    listener=socket.socket();listener.bind(("127.0.0.1",0));listener.listen(1)
    listener.settimeout(3)
    ready=threading.Event();finish=threading.Event()
    def broker():
        connection,_=listener.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(b"\x20\x02\x00\x00")
            finish.wait(3)
    thread=threading.Thread(target=broker,daemon=True);thread.start()
    publisher=MqttPublisher(port=listener.getsockname()[1])
    publisher.client.on_connect=lambda *args:ready.set()
    try:
        publisher.connect();assert ready.wait(2)
        accepted=sum(publisher.publish({"event":"test","payload":"x"*1024}).ok for _ in range(100))
        assert accepted<=16
    finally:
        finish.set();publisher.close();thread.join(timeout=3);listener.close()

def test_status_distinguishes_disabled_disconnected_and_failed_publish():
    from edgevision.mqtt_client import MqttPublisher
    disabled = MqttPublisher(enabled=False)
    assert disabled.status()["state"] == "disabled"
    publisher = MqttPublisher()
    try:
        assert publisher.status()["state"] == "disconnected"
        assert not publisher.publish({"event_id": "offline"}).ok
        status = publisher.status()
        assert status["accepted"] == 0
        assert status["failed"] == 1
        assert status["event_status"]["offline"]["state"] == "failed"
        assert status["event_status"]["offline"]["error"] == "disconnected"
    finally:
        disabled.close()
        publisher.close()

@pytest.mark.parametrize('disconnect_race', [False, True])
def test_qos1_status_requires_real_broker_puback(disconnect_race, monkeypatch):
    import threading
    from edgevision.mqtt_client import MqttPublisher
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3)
    connected = threading.Event()
    allow_ack = threading.Event()
    finish = threading.Event()
    failures = []

    def packet(connection):
        def take(size):
            data = b""
            while len(data) < size:
                part = connection.recv(size - len(data))
                if not part:
                    raise EOFError("MQTT connection closed")
                data += part
            return data
        kind = take(1)[0]
        remaining = 0
        multiplier = 1
        while True:
            digit = take(1)[0]
            remaining += (digit & 127) * multiplier
            if not digit & 128:
                break
            multiplier *= 128
        return kind, take(remaining)

    def broker():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(3)
                assert packet(connection)[0] == 0x10
                connection.sendall(bytes([0x20, 2, 0, 0]))
                connected.set()
                kind, body = packet(connection)
                assert kind == 0x32
                topic_length = int.from_bytes(body[:2], "big")
                mid = body[2 + topic_length:4 + topic_length]
                assert allow_ack.wait(3)
                connection.sendall(bytes([0x40, 2]) + mid)
                finish.wait(3)
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=broker, daemon=True)
    thread.start()
    publisher = MqttPublisher(port=listener.getsockname()[1])
    try:
        if disconnect_race:
            original_send = publisher.client._send_publish
            monkeypatch.setattr(publisher.client, 'is_connected', lambda: True)
            monkeypatch.setattr(publisher.client, '_send_publish', lambda *args, **kwargs: 4)
            assert publisher.publish({'event_id': 'evt-live'}).ok
            assert publisher.status()['event_status']['evt-live']['state'] == 'pending'
            monkeypatch.setattr(publisher.client, '_send_publish', original_send)
            monkeypatch.undo()
        publisher.connect()
        assert connected.wait(2)
        deadline = time.monotonic() + 2
        while not publisher.client.is_connected() and time.monotonic() < deadline:
            time.sleep(.01)
        if not disconnect_race:
            assert publisher.publish({"event_id": "evt-live"}).ok
        status = publisher.status()
        assert status["state"] == "connected"
        assert status["accepted"] == 1
        assert status["acknowledged"] == 0
        assert status["pending"] == 1
        assert status["event_status"]["evt-live"]["state"] == "pending"
        allow_ack.set()
        deadline = time.monotonic() + 2
        while publisher.status()["acknowledged"] != 1 and time.monotonic() < deadline:
            time.sleep(.01)
        status = publisher.status()
        assert status["acknowledged"] == 1
        assert status["pending"] == 0
        assert status["event_status"]["evt-live"]["state"] == "acknowledged"
        assert not failures
    finally:
        allow_ack.set()
        finish.set()
        publisher.close()
        thread.join(timeout=3)
        listener.close()

def test_puback_before_publish_returns_is_not_lost(monkeypatch):
    from types import SimpleNamespace
    from edgevision.mqtt_client import MqttPublisher
    publisher = MqttPublisher()
    monkeypatch.setattr(publisher.client, "is_connected", lambda: True)
    def acknowledged_publish(*args, **kwargs):
        publisher.client.on_publish(publisher.client, None, 7,
                                    SimpleNamespace(is_failure=False), None)
        return SimpleNamespace(rc=0, mid=7)
    monkeypatch.setattr(publisher.client, "publish", acknowledged_publish)
    try:
        assert publisher.publish({"event_id": "early"}).ok
        status = publisher.status()
        assert status["accepted"] == status["acknowledged"] == 1
        assert status["pending"] == 0
        assert status["event_status"]["early"]["state"] == "acknowledged"
    finally:
        publisher.close()

def test_publish_does_not_hold_status_lock_while_paho_invokes_callback(monkeypatch):
    from types import SimpleNamespace
    import threading
    from edgevision.mqtt_client import MqttPublisher
    publisher = MqttPublisher()
    monkeypatch.setattr(publisher.client, "is_connected", lambda: True)
    done = threading.Event()
    def publish(*args, **kwargs):
        def callback():
            publisher.client.on_publish(publisher.client, None, 12,
                                        SimpleNamespace(is_failure=False), None)
            done.set()
        thread = threading.Thread(target=callback, daemon=True)
        thread.start()
        if not done.wait(.3):
            raise RuntimeError("application lock blocks Paho callback")
        return SimpleNamespace(rc=0, mid=12)
    monkeypatch.setattr(publisher.client, "publish", publish)
    try:
        assert publisher.publish({"event_id": "concurrent"}).ok
        assert publisher.status()["acknowledged"] == 1
    finally:
        publisher.close()
def test_receiver_deduplicates_across_restart(tmp_path):
    import json
    import sqlite3
    from edgevision.receiver import record_receipt
    path = tmp_path / "subscriber.db"
    payload = json.dumps({"event_id": "one"}).encode()
    with sqlite3.connect(path) as first:
        assert record_receipt(first, payload)
    with sqlite3.connect(path) as second:
        assert not record_receipt(second, payload)
        assert second.execute("SELECT event_id FROM receipts").fetchall() == [("one",)]
