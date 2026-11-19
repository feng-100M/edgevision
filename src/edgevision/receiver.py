"""Duty-station QoS 1 subscriber. The SQLite row is the durable local receipt."""
import json
import logging
import re
import sqlite3
from contextlib import closing

import paho.mqtt.client as mqtt


def record_receipt(db, payload):
    body = json.loads(payload)
    key = body.get("event_id") if isinstance(body, dict) else None
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key):
        raise ValueError("Invalid MQTT event_id")
    with db:
        db.execute("""CREATE TABLE IF NOT EXISTS receipts
                      (event_id TEXT PRIMARY KEY, received_at TEXT DEFAULT CURRENT_TIMESTAMP,
                       payload TEXT NOT NULL)""")
        cursor = db.execute("INSERT OR IGNORE INTO receipts(event_id, payload) VALUES (?, ?)",
                            (key, json.dumps(body, ensure_ascii=False)))
    return cursor.rowcount == 1


def receive(config, path, client_id):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                             clean_session=False, manual_ack=True)

        def connected(client, userdata, flags, reason_code, properties):
            if not reason_code.is_failure:
                client.subscribe(config.topic, qos=1)

        def message(client, userdata, msg):
            try:
                fresh = record_receipt(db, msg.payload)
            except ValueError as exc:
                logging.warning("Ignoring malformed alert: %s", exc)
            else:
                if fresh:
                    print(msg.payload.decode("utf8"), flush=True)
            client.ack(msg.mid, msg.qos)

        client.on_connect = connected
        client.on_message = message
        client.connect_async(config.host, config.port)
        try:
            client.loop_forever(retry_first_connection=True)
        except KeyboardInterrupt:
            pass
        finally:
            client.disconnect()
