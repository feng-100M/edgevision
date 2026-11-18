"""尽力而为的非阻塞 MQTT 发布器，带有界在途消息和自动重连。

MQTT 是告警的旁路输出；Broker 不可用时 ``publish`` 返回失败结果，
本地截图、JSONL 和检测主循环仍然继续运行。

连接和重连由 Paho 后台线程完成，主线程只做一次尽力而为的发布尝试；
因此 MQTT 的可用性影响指标和日志，不改变本地事件是否已经落盘。
"""
from dataclasses import dataclass
from collections import OrderedDict
import threading
import json
import logging
from uuid import uuid4
import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishResult:
    """记录一次发布是否成功以及可供指标/日志使用的原因。"""
    ok: bool
    error: str = ""


class MqttPublisher:
    """封装 Paho 后台网络线程，限制待发送和在途消息数量。"""

    def __init__(
            self,
            host="127.0.0.1",
            port=1883,
            topic="edgevision/alerts",
            enabled=True):
        self.host = host
        self.port = port
        self.topic = topic
        self.enabled = enabled
        self.started = False
        self._lock = threading.RLock()
        self._publish_lock = threading.Lock()
        self._accepted = 0
        self._acknowledged = 0
        self._failed = 0
        self._pending = {}
        self._recent = OrderedDict()
        self._publishing = False
        self._early_ack = {}
        self._last_error = ""
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="edgevision-" + uuid4().hex[:8])
        self.client.reconnect_delay_set(min_delay=1, max_delay=15)
        self.client.max_queued_messages_set(16)
        self.client.max_inflight_messages_set(4)
        self.client.enable_logger(LOG)
        self.client.on_publish = self._on_publish

    def _remember(self, event_id, state, error=""):
        if event_id:
            self._recent[event_id] = {"state": state, "error": error}
            self._recent.move_to_end(event_id)
            while len(self._recent) > 64:
                self._recent.popitem(last=False)

    def _confirm(self, event_id, failed, error):
        if failed:
            self._failed += 1
            self._last_error = error
            self._remember(event_id, "failed", error)
        else:
            self._acknowledged += 1
            self._remember(event_id, "acknowledged")

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        # 此回调才代表 QoS1 Broker 确认，不能用 publish 返回码代替。
        failed = bool(getattr(reason_code, "is_failure", False))
        error = str(reason_code) if failed else ""
        with self._lock:
            if mid in self._pending:
                self._confirm(self._pending.pop(mid), failed, error)
            elif self._publishing:
                # 兼容确认先于 publish 返回的情况；每次发布后立即清空。
                self._early_ack[mid] = (failed, error)

    def status(self):
        """返回本次运行的连接、客户端接收和 Broker 确认状态快照。"""
        with self._lock:
            state = "disabled" if not self.enabled else (
                "connected" if self.client.is_connected() else "disconnected")
            return {"state": state, "enabled": self.enabled,
                    "host": self.host, "port": self.port, "topic": self.topic,
                    "accepted": self._accepted, "acknowledged": self._acknowledged,
                    "pending": len(self._pending), "failed": self._failed,
                    "last_error": self._last_error,
                    "event_status": {key: dict(value) for key, value in self._recent.items()}}

    def connect(self):
        """启动异步连接和 Paho 网络线程；连接失败由 Paho 重试。"""
        if self.enabled and not self.started:
            # connect_async 不阻塞启动；网络线程负责建立连接和后续重连。
            self.client.connect_async(self.host, self.port, keepalive=30)
            self.client.loop_start()
            self.started = True

    def publish(self, event):
        """尝试以 QoS 1 发布事件，绝不把 Broker 异常抛给主循环。"""
        # 先检查开关和连接状态，避免在 Broker 不可达时把每帧处理拖进网络等待。
        body = event.to_dict() if hasattr(event, "to_dict") else event
        event_id = body.get("event_id", "")
        # Paho 回调可能持有其内部锁，调用 publish 时不能同时持有状态锁。
        with self._publish_lock:
            error = ""
            if not self.enabled:
                with self._lock:
                    self._remember(event_id, "disabled")
                return PublishResult(False, "disabled")
            if not self.client.is_connected():
                error = "disconnected"
            elif len(self._pending) >= 16:
                error = "queue_full"
            else:
                try:
                    with self._lock:
                        self._publishing = True
                    info = self.client.publish(self.topic, json.dumps(
                        body, ensure_ascii=False), qos=1, retain=False)
                    # Paho may enqueue a QoS1 packet while disconnected and
                    # return MQTT_ERR_NO_CONN.  When it has a message id, that
                    # packet remains in Paho's reconnect queue and its eventual
                    # on_publish callback is the real delivery confirmation.
                    # Treating it as an immediate failure loses the event and
                    # leaves the later PUBACK unaccounted for.
                    accepted_rc = info.rc == mqtt.MQTT_ERR_SUCCESS or (
                        info.rc == mqtt.MQTT_ERR_NO_CONN and
                        isinstance(getattr(info, "mid", None), int) and info.mid > 0)
                    if accepted_rc:
                        with self._lock:
                            self._accepted += 1
                            self._last_error = ""
                            self._remember(event_id, "pending")
                            if info.mid in self._early_ack:
                                self._confirm(event_id, *self._early_ack[info.mid])
                            else:
                                self._pending[info.mid] = event_id
                        return PublishResult(True)
                    error = mqtt.error_string(info.rc)
                except (OSError, ValueError, RuntimeError, TypeError) as exc:
                    error = str(exc)
                finally:
                    with self._lock:
                        self._publishing = False
                        self._early_ack.clear()
            with self._lock:
                self._failed += 1
                self._last_error = error
                self._remember(event_id, "failed", error)
            return PublishResult(False, error)

    def close(self):
        """停止网络线程并关闭连接。"""
        if self.started:
            # 退出时先断开再停止线程，避免后台线程继续使用已经结束的流水线资源。
            self.client.disconnect()
            self.client.loop_stop()
            self.started = False
