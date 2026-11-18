from queue import Empty
import threading
import time

import pytest

from edgevision.types import Frame


def frame(sequence, captured_at=None):
    return Frame(sequence, time.monotonic() if captured_at is None else captured_at, object(), "clip")


def test_full_queue_replaces_the_stale_frame_instead_of_blocking():
    from edgevision.frame_queue import LatestFrameQueue

    queue = LatestFrameQueue(maxsize=1)
    for sequence in range(100):
        queue.put(frame(sequence))
        assert queue.qsize() == 1
    assert queue.get(timeout=0).seq == 99
    assert queue.dropped_count == 99


def test_larger_queue_retains_only_the_newest_bounded_window_in_fifo_order():
    from edgevision.frame_queue import LatestFrameQueue

    queue = LatestFrameQueue(maxsize=2)
    queue.put(frame(1))
    queue.put(frame(2))
    queue.put(frame(3))
    assert [queue.get(timeout=0).seq, queue.get(timeout=0).seq] == [2, 3]
    assert queue.dropped_count == 1


def test_empty_queue_raises_standard_empty_exception_on_timeout():
    from edgevision.frame_queue import LatestFrameQueue

    queue = LatestFrameQueue()
    with pytest.raises(Empty):
        queue.get(timeout=0)
    with pytest.raises(Empty):
        queue.get(timeout=.001)


def test_close_drains_the_final_frame_then_raises_closed():
    from edgevision.frame_queue import LatestFrameQueue, QueueClosed

    queue = LatestFrameQueue()
    queue.put(frame(1))
    queue.close()
    queue.close()
    assert queue.get(timeout=0).seq == 1
    with pytest.raises(QueueClosed):
        queue.get()
    with pytest.raises(QueueClosed):
        queue.put(frame(2))


def test_close_wakes_waiting_consumer_without_a_sentinel_frame():
    from edgevision.frame_queue import LatestFrameQueue, QueueClosed

    queue = LatestFrameQueue()
    started = threading.Event()
    stopped = threading.Event()
    failures = []

    def consume():
        started.set()
        try:
            queue.get()
            failures.append("Expected QueueClosed")
        except QueueClosed:
            stopped.set()
        except BaseException as error:
            failures.append(error)

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    assert started.wait(timeout=1)
    queue.close()
    consumer.join(timeout=1)
    assert not consumer.is_alive()
    assert stopped.is_set()
    assert failures == []


def test_producer_put_wakes_consumer():
    from edgevision.frame_queue import LatestFrameQueue

    queue = LatestFrameQueue()
    started = threading.Event()
    received = []

    def consume():
        started.set()
        received.append(queue.get(timeout=1))

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    assert started.wait(timeout=1)
    queue.put(frame(7))
    consumer.join(timeout=1)
    queue.close()
    assert not consumer.is_alive()
    assert [value.seq for value in received] == [7]


def test_queue_reports_max_dequeued_frame_age_in_seconds():
    from edgevision.frame_queue import LatestFrameQueue

    queue = LatestFrameQueue()
    assert queue.max_frame_age == 0
    queue.put(frame(1, time.monotonic() - 2))
    queue.get(timeout=0)
    assert queue.max_frame_age >= 2
    oldest_age = queue.max_frame_age
    queue.put(frame(2))
    queue.get(timeout=0)
    assert queue.max_frame_age == oldest_age


@pytest.mark.parametrize("maxsize", [0, -1, 1.5])
def test_queue_rejects_invalid_capacity(maxsize):
    from edgevision.frame_queue import LatestFrameQueue

    with pytest.raises(ValueError):
        LatestFrameQueue(maxsize=maxsize)


def test_queue_rejects_negative_timeout():
    from edgevision.frame_queue import LatestFrameQueue

    with pytest.raises(ValueError):
        LatestFrameQueue().get(timeout=-1)


def test_queue_residence_excludes_time_before_enqueue(monkeypatch):
    from edgevision import frame_queue
    clock = [10.]
    monkeypatch.setattr(frame_queue.time, "monotonic", lambda: clock[0])
    queue = frame_queue.LatestFrameQueue()
    assert queue.wait_p95_ms is None
    queue.put(frame(1, captured_at=5.))
    clock[0] += .020
    queue.get()
    assert queue.wait_p95_ms == 20
    assert queue.max_frame_age == pytest.approx(5.020)
