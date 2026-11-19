import json
from dataclasses import asdict
from datetime import datetime, timezone
import numpy as np
import pytest

def event(event_id="evt-1"):
    from edgevision.types import Event
    return Event(event_id=event_id,event_type="person_entered",
                 occurred_at=datetime.now(timezone.utc).isoformat(),confidence=.8,
                 roi_name="roi",bbox=(1,2,3,4),snapshot_path="",
                 source_name="video",track_id=1,source_time=1.)

def test_event_snapshot_and_json_are_consistent(tmp_path):
    from edgevision.storage import EventStorage
    store=EventStorage(tmp_path,max_bytes=500000,min_free_bytes=0)
    e=event()
    store.save(e,np.zeros((40,40,3),np.uint8))
    records=list(tmp_path.rglob("events.jsonl"))
    loaded=json.loads(records[0].read_text().splitlines()[0])
    assert loaded["event_id"] == e.event_id
    assert (tmp_path/loaded["snapshot_path"]).is_file()
    import cv2
    assert cv2.imdecode(np.fromfile(tmp_path/loaded["snapshot_path"],dtype=np.uint8),cv2.IMREAD_COLOR).shape == (40,40,3)

def test_event_metadata_can_be_saved_without_a_blurry_snapshot(tmp_path):
    from edgevision.storage import EventStorage
    stored = event("blurred")
    EventStorage(tmp_path, min_free_bytes=0).save(stored, None)
    rows = EventStorage(tmp_path, min_free_bytes=0).recent_events()
    assert rows[0]["event_id"] == "blurred"
    assert rows[0]["snapshot_path"] is None
    assert EventStorage(tmp_path, min_free_bytes=0).snapshot("blurred") is None

def test_disk_budget_removes_old_records_including_same_day(tmp_path):
    from edgevision.storage import EventStorage
    store=EventStorage(tmp_path,max_bytes=2300,min_free_bytes=0)
    for i in range(8):
        store.save(event(f"evt-{i}"),np.zeros((20,20,3),np.uint8))
    assert sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file()) <= 2300
    records=[json.loads(line) for p in tmp_path.rglob("events.jsonl") for line in p.read_text().splitlines()]
    assert records[-1]["event_id"] == "evt-7"
    for row in records:
        assert (tmp_path/row["snapshot_path"]).exists()

def test_event_id_cannot_escape_storage_root(tmp_path):
    from edgevision.storage import EventStorage, StorageError
    with pytest.raises(StorageError):
        EventStorage(tmp_path,min_free_bytes=0).save(event("../../escape"),np.zeros((10,10,3),np.uint8))
    assert not (tmp_path.parent/"escape.jpg").exists()

def test_too_large_current_event_rejected_without_partial_files(tmp_path):
    from edgevision.storage import EventStorage, StorageError
    with pytest.raises(StorageError):
        EventStorage(tmp_path,max_bytes=50,min_free_bytes=0).save(event(),np.zeros((10,10,3),np.uint8))
    assert not list(tmp_path.rglob("*.jpg"))

def test_metadata_write_failure_rolls_back_new_snapshot(tmp_path,monkeypatch):
    from edgevision.storage import EventStorage,StorageError
    store=EventStorage(tmp_path,min_free_bytes=0)
    def fail(*args):raise OSError("Injected metadata failure")
    monkeypatch.setattr(store,"_rewrite",fail)
    with pytest.raises(StorageError):
        store.save(event(),np.zeros((20,20,3),np.uint8))
    assert not list(tmp_path.rglob("*.jpg"))

def test_retention_write_failure_preserves_referenced_snapshot(tmp_path,monkeypatch):
    from edgevision.storage import EventStorage,StorageError
    store=EventStorage(tmp_path,min_free_bytes=0)
    first=event("first");store.save(first,np.zeros((20,20,3),np.uint8))
    store.max_bytes=1400
    def fail(*args):raise OSError("Injected retention write failure")
    monkeypatch.setattr(store,"_rewrite",fail)
    with pytest.raises(StorageError):
        store.save(event("second"),np.zeros((20,20,3),np.uint8))
    assert (tmp_path/first.snapshot_path).is_file()

def test_forged_event_record_cannot_delete_unrelated_file(tmp_path):
    from edgevision.storage import EventStorage,StorageError
    folder=tmp_path/"2020-01-01";folder.mkdir()
    unrelated=tmp_path/"unrelated.onnx";unrelated.write_bytes(b"preserve")
    row=event().to_dict();row["occurred_at"]="2020-01-01T00:00:00Z"
    row["snapshot_path"]="unrelated.onnx"
    (folder/"events.jsonl").write_text(json.dumps(row)+"\n")
    with pytest.raises(StorageError):
        EventStorage(tmp_path,min_free_bytes=0).save(event("new"),np.zeros((20,20,3),np.uint8))
    assert unrelated.read_bytes()==b"preserve"

def test_recent_events_and_snapshot_survive_reopening_storage(tmp_path):
    from edgevision.storage import EventStorage
    store = EventStorage(tmp_path, min_free_bytes=0)
    first = event("first")
    second = event("second")
    store.save(first, np.zeros((20,20,3),np.uint8))
    store.save(second, np.zeros((20,20,3),np.uint8))
    reopened = EventStorage(tmp_path, min_free_bytes=0)
    assert [row["event_id"] for row in reopened.recent_events(1)] == ["second"]
    assert reopened.snapshot("first").startswith(bytes([255,216]))
    assert reopened.snapshot("missing") is None
    assert reopened.recent_events(0) == []

def test_snapshot_lookup_rejects_traversal_and_tampered_record(tmp_path):
    from edgevision.storage import EventStorage, StorageError
    store = EventStorage(tmp_path, min_free_bytes=0)
    stored = event()
    store.save(stored, np.zeros((20,20,3),np.uint8))
    with pytest.raises(StorageError):
        store.snapshot("../../config")
    records = next(tmp_path.rglob("events.jsonl"))
    row = json.loads(records.read_text())
    row["snapshot_path"] = "../config.local.yaml"
    records.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(StorageError):
        store.snapshot(stored.event_id)

def test_snapshot_lookup_rejects_link_in_parent_directory(tmp_path):
    from edgevision.storage import EventStorage, StorageError
    outside = tmp_path / "other"
    outside.mkdir()
    linked = tmp_path / "2026-10-29"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    row = event("linked").to_dict()
    row["snapshot_path"] = "2026-10-29/linked.jpg"
    (outside / "events.jsonl").write_text(json.dumps(row), encoding="utf-8")
    (outside / "linked.jpg").write_bytes(b"private")
    with pytest.raises(StorageError):
        EventStorage(tmp_path, min_free_bytes=0).snapshot("linked")

@pytest.mark.parametrize('invalid', [[], {'event_id': 2}, {'event_id': 'bad', 'occurred_at': 2}])
def test_invalid_record_structure_becomes_storage_error(tmp_path, invalid):
    from edgevision.storage import EventStorage, StorageError
    folder = tmp_path / '2026-10-29'
    folder.mkdir()
    (folder / 'events.jsonl').write_text(json.dumps(invalid), encoding='utf-8')
    with pytest.raises(StorageError):
        EventStorage(tmp_path, min_free_bytes=0).recent_events()

def test_slow_history_scan_does_not_hold_save_lock(tmp_path, monkeypatch):
    import threading
    from edgevision.storage import EventStorage
    store = EventStorage(tmp_path, min_free_bytes=0)
    entered = threading.Event()
    release = threading.Event()
    saved = threading.Event()
    writer_done = threading.Event()
    def slow_rows():
        entered.set()
        assert release.wait(2)
        return []
    monkeypatch.setattr(store, '_rows', slow_rows)
    monkeypatch.setattr(store, '_save', lambda *args: saved.set())
    reader = threading.Thread(target=store.recent_events, daemon=True)
    def write():
        store.save(None, None)
        writer_done.set()
    writer = threading.Thread(target=write, daemon=True)
    reader.start()
    try:
        assert entered.wait(1)
        writer.start()
        assert saved.wait(.3), 'history reading blocked detection event save'
        assert writer_done.wait(.3), 'save() waited for the slow history scan'
    finally:
        release.set()
        reader.join(2)
        if writer.ident is not None:
            writer.join(2)

def test_history_and_thumbnails_reuse_index_until_log_changes(tmp_path, monkeypatch):
    from edgevision.storage import EventStorage
    store = EventStorage(tmp_path, min_free_bytes=0)
    store.save(event('first'), np.zeros((20,20,3), np.uint8))
    original = store._rows
    calls = []
    def counted():
        calls.append(1)
        return original()
    monkeypatch.setattr(store, '_rows', counted)
    store.recent_events()
    store.snapshot('first')
    store.snapshot('first')
    assert len(calls) == 1
    store.save(event('second'), np.zeros((20,20,3), np.uint8))
    calls.clear()
    assert len(store.recent_events()) == 2
    store.snapshot('second')
    assert len(calls) == 1
def test_impossible_quota_preserves_evidence_and_foreign_log(tmp_path):
    from edgevision.storage import EventStorage, StorageError
    store = EventStorage(tmp_path, max_bytes=4096, min_free_bytes=0)
    store.save(event("old"), np.zeros((20, 20, 3), np.uint8))
    before = store.snapshot("old")
    (tmp_path / "unmanaged.bin").write_bytes(b"x" * 4100)
    with pytest.raises(StorageError):
        store.save(event("new"), None)
    assert [row["event_id"] for row in store.recent_events()] == ["old"]
    assert store.snapshot("old") == before
    assert store.cleaned_events == 0

def test_unconfirmed_events_are_protected_until_durable_ack(tmp_path):
    from edgevision.storage import EventStorage, StorageError
    store = EventStorage(tmp_path, max_bytes=650, min_free_bytes=0)
    store.queue_delivery = True
    store.save(event("old"), None)
    with pytest.raises(StorageError):
        store.save(event("new"), None)
    assert [row["event_id"] for row in store.pending_events()] == ["old"]
    store.acknowledge({"old"})
    reopened = EventStorage(tmp_path, max_bytes=650, min_free_bytes=0)
    assert not reopened.pending_events()
    reopened.save(event("new"), None)
    assert reopened.recent_events()[0]["event_id"] == "new"

def test_full_diagnostics_directory_does_not_consume_event_quota(tmp_path):
    from edgevision.storage import EventStorage
    store = EventStorage(tmp_path / "events", max_bytes=4096, min_free_bytes=0)
    store.save(event("old"), None)
    diagnostics = tmp_path / "diagnostics"
    diagnostics.mkdir()
    (diagnostics / "frames.csv").write_bytes(b"x" * 4100)
    store.save(event("new"), None)
    assert {row["event_id"] for row in store.recent_events()} == {"old", "new"}

def test_async_snapshot_preserves_ack_and_updates_history(tmp_path):
    from edgevision.storage import EventStorage
    store = EventStorage(tmp_path, min_free_bytes=0)
    store.queue_delivery = True
    record = event("photo")
    store.save(record, None)
    store.acknowledge({"photo"})
    assert store.attach_snapshot(record, np.zeros((20, 20, 3), np.uint8))
    assert store.snapshot("photo").startswith(b"\xff\xd8")
    assert store.recent_events()[0]["delivery_state"] == "acked"

def test_legacy_service_trace_does_not_disable_upgraded_service(tmp_path):
    from edgevision.storage import EventStorage
    store = EventStorage(tmp_path, max_bytes=4096, min_free_bytes=0)
    store.save(event("old"), np.zeros((20, 20, 3), np.uint8))
    legacy = tmp_path / "service-frames.csv"
    legacy.write_bytes(b"x" * 4100)
    store.save(event("new"), np.zeros((20, 20, 3), np.uint8))
    assert {row["event_id"] for row in store.recent_events()} == {"old", "new"}
    assert legacy.stat().st_size == 4100

def test_failed_replacement_event_write_keeps_old_evidence(tmp_path, monkeypatch):
    from edgevision.storage import EventStorage, StorageError
    store = EventStorage(tmp_path, max_bytes=1500, min_free_bytes=0)
    store.save(event("old"), np.zeros((20, 20, 3), np.uint8))
    rewrite = store._rewrite
    def fail_new(log, rows):
        if any(row["event_id"] == "new" for row in rows):
            raise OSError("disk unavailable")
        rewrite(log, rows)
    monkeypatch.setattr(store, "_rewrite", fail_new)
    with pytest.raises(StorageError):
        store.save(event("new"), np.zeros((20, 20, 3), np.uint8))
    assert store.snapshot("old")
