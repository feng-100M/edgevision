import time
import json
import numpy as np
from edgevision.types import Frame,Detection
from edgevision.config import load_config
from pathlib import Path

class Frames:
    start_time=None
    reconnects=0
    def __iter__(self):
        self.start_time=time.monotonic()
        for i,x in enumerate([32,41,44,32]):
            yield Frame(i,time.monotonic(),np.zeros((100,100,3),np.uint8),"synthetic",i*.1)
    def close(self):
        pass

class Boxes:
    last_inference_ms=1.
    def __init__(self,fail_first=False):
        self.i=0;self.fail_first=fail_first
    def detect(self,image):
        i=self.i;self.i+=1
        if i==0 and self.fail_first:
            raise RuntimeError("Injected inference error")
        x=[32,41,44,32][i]
        return [Detection(x-4,10,x+4,50,.9)]

def config(tmp_path):
    cfg=load_config(Path(__file__).parents[1]/"config.example.yaml")
    cfg.output.directory=tmp_path
    cfg.output.min_free_bytes=0
    cfg.mqtt.enabled=False
    cfg.roi.points=[[.4,0],[.9,0],[.9,.9],[.4,.9]]
    cfg.events.cooldown_seconds=0.
    return cfg

def test_pipeline_generates_enter_leave_and_persists(tmp_path):
    from edgevision.pipeline import Pipeline
    p=Pipeline(config(tmp_path),Frames(),Boxes())
    summary=p.run(mode="sync")
    rows=[json.loads(line) for f in tmp_path.rglob("events.jsonl") for line in f.read_text().splitlines()]
    assert [r["event_type"] for r in rows] == ["person_entered","person_left"]
    assert summary["processed_frames"]==4
    assert summary["events"]==2
    assert summary["errors"]==0
    assert summary["event_end_to_end_p95_ms"] is not None

def test_blurry_event_is_recorded_without_blocking_snapshot_write(tmp_path):
    from edgevision.pipeline import Pipeline
    summary = Pipeline(config(tmp_path), Frames(), Boxes()).run(mode="sync")
    assert summary["focus_rejected"] == 2
    assert summary["snapshot_saved"] == 0
    assert summary["snapshot_skipped"] == 2
    assert summary["event_output_p95_ms"] is not None

def test_single_frame_failure_does_not_abort_replay(tmp_path):
    from edgevision.pipeline import Pipeline
    summary=Pipeline(config(tmp_path),Frames(),Boxes(True)).run(mode="sync")
    assert summary["processed_frames"]==3
    assert summary["errors"]==1

def test_latest_pipeline_bounded_and_shuts_down(tmp_path):
    from edgevision.pipeline import Pipeline
    summary=Pipeline(config(tmp_path),Frames(),Boxes()).run(mode="latest")
    assert summary["capture_frames"]==4
    assert summary["processed_frames"]+summary["queue_dropped_frames"]==4
    assert summary["max_queue_size"]<=1

def test_evaluation_matches_each_truth_once_and_counts_duplicates():
    from edgevision.evaluation import evaluate_events
    truth=[{"event_type":"person_entered","source_time":1.,"roi_name":"roi"}]
    predicted=[{"event_type":"person_entered","source_time":t,"roi_name":"roi"} for t in [1.1,1.2,5.]]
    scores=evaluate_events(predicted,truth,window_seconds=.5)
    assert scores["tp"]==1 and scores["fp"]==2 and scores["fn"]==0
    assert scores["duplicates"]==1
    assert scores["precision"] == 1/3

def test_evaluation_never_matches_wrong_roi():
    from edgevision.evaluation import evaluate_events
    truth=[{"event_type":"person_entered","source_time":1.,"roi_name":"a"}]
    predicted=[{"event_type":"person_entered","source_time":1.,"roi_name":"b"}]
    scores=evaluate_events(predicted,truth)
    assert scores["tp"]==0 and scores["fn"]==1 and scores["fp"]==1

def test_matching_maximizes_true_positives_before_nearest_tie_break():
    from edgevision.evaluation import evaluate_events
    predicted=[{"event_type":"person_entered","source_time":t,"roi_name":"roi"} for t in [.19,.4]]
    truth=[{"event_type":"person_entered","source_time":t,"roi_name":"roi"} for t in [0,.2]]
    result=evaluate_events(predicted,truth,window_seconds=.3)
    assert result["tp"]==2 and result["fp"]==0 and result["fn"]==0

def test_frame_budget_does_not_request_an_additional_frame(tmp_path):
    from edgevision.pipeline import Pipeline
    class OneFrame(Frames):
        def __iter__(self):
            yield Frame(0,time.monotonic(),np.zeros((100,100,3),np.uint8),"one",0.)
            raise AssertionError("Requested an extra frame beyond the budget")
    result=Pipeline(config(tmp_path),OneFrame(),Boxes()).run(mode="sync",max_frames=1)
    assert result["processed_frames"]==1

def test_duration_closes_idle_sync_source(tmp_path):
    from edgevision.pipeline import Pipeline
    import threading
    class Idle(Frames):
        def __init__(self):self.closed=threading.Event()
        def __iter__(self):
            self.closed.wait(1)
            return
            yield
        def close(self):self.closed.set()
    started=time.monotonic()
    Pipeline(config(tmp_path),Idle(),Boxes()).run(mode="sync",duration=.05)
    assert time.monotonic()-started<.5

def test_pipeline_rotates_pixels_before_the_detector(tmp_path):
    from edgevision.pipeline import Pipeline
    class PixelSource(Frames):
        def __iter__(self):
            image=np.zeros((100,100,3),np.uint8)
            image[-1,-1]=[40,50,60]
            yield Frame(0,time.monotonic(),image,"rotation",0.)
    class InspectDetector:
        last_inference_ms=1.
        def detect(self,image):
            assert image[0,0].tolist()==[40,50,60]
            return []
    cfg=config(tmp_path);cfg.input.rotation=180
    result=Pipeline(cfg,PixelSource(),InspectDetector()).run(mode="sync")
    assert result["processed_frames"]==1 and result["errors"]==0

def test_pipeline_mirror_is_shared_by_detector_and_preview(tmp_path):
    from edgevision.pipeline import Pipeline
    class PixelSource(Frames):
        def __iter__(self):
            image=np.zeros((100,100,3),np.uint8);image[-1,-1]=[40,50,60]
            yield Frame(0,time.monotonic(),image,"mirror",0.)
    class Detector:
        last_inference_ms=1.
        def detect(self,image):
            assert image[0,-1].tolist()==[40,50,60]
            return []
    class Preview:
        def update(self,frame,*args):
            assert frame.image[0,-1].tolist()==[40,50,60]
    cfg=config(tmp_path);cfg.input.rotation=180;cfg.input.mirror_horizontal=True
    result=Pipeline(cfg,PixelSource(),Detector(),Preview()).run(mode="sync")
    assert result["processed_frames"]==1 and result["errors"]==0
    assert result["input_mirror_horizontal"] is True

def test_preview_explains_outside_bottom_clipped_box_and_mqtt_state(tmp_path):
    from edgevision.pipeline import Pipeline
    class Detector:
        last_inference_ms=1.
        def detect(self,image):
            return [Detection(40,10,60,100,.9)]
    class Preview:
        def update(self, frame, detections, tracks, events, polygon, metrics):
            assert events == []
            assert metrics['inside_count'] == 0
            assert metrics['track_diagnostics'][0]['reason'] == 'outside_roi'
            assert metrics['track_diagnostics'][0]['bottom_clipped'] is True
    cfg=config(tmp_path)
    result=Pipeline(cfg,Frames(),Detector(),Preview()).run(mode='sync',max_frames=1)
    assert result['errors'] == 0
    assert result['mqtt_acknowledged'] == 0
    assert result['mqtt_pending'] == 0

def test_disabled_roi_treats_full_frame_as_detection_area(tmp_path):
    from edgevision.pipeline import Pipeline
    class Preview:
        def update(self, frame, detections, tracks, events, polygon, metrics):
            assert metrics['roi_enabled'] is False
            assert metrics['roi_name'] == '全画面'
            assert metrics['track_diagnostics'][0]['inside'] is True
            assert metrics['track_diagnostics'][0]['reason'] == 'entered'
            assert events and events[0].roi_name == '全画面'
    cfg = config(tmp_path)
    cfg.roi.enabled = False
    result = Pipeline(cfg, Frames(), Boxes(), Preview()).run(mode='sync', max_frames=1)
    assert result['events'] == 1


def test_output_failure_preserves_later_events_and_finishes(tmp_path, monkeypatch):
    import threading
    from edgevision.pipeline import Pipeline

    pipeline = Pipeline(config(tmp_path), Frames(), Boxes())
    save = pipeline.storage.save
    def fail_first(event, image):
        if event.event_type == "person_entered":
            raise OSError("injected media error")
        return save(event, image)
    monkeypatch.setattr(pipeline.storage, "save", fail_first)
    summary = {}
    runner = threading.Thread(target=lambda: summary.update(pipeline.run(mode="sync")), daemon=True)
    runner.start()
    runner.join(timeout=3)
    assert not runner.is_alive(), "failed event output blocked shutdown"
    assert summary["storage_failed"] == 1
    assert [row["event_type"] for row in pipeline.storage.recent_events()] == ["person_left"]


def test_latest_measures_residence_and_ipc_skips_separately(tmp_path):
    from edgevision.pipeline import Pipeline
    source = Frames()
    source.driver_dropped_frames = 7
    summary = Pipeline(config(tmp_path), source, Boxes()).run(mode="latest")
    assert summary["camera_ipc_skipped_frames"] == summary["camera_driver_dropped_frames"] == 7
    assert summary["app_queue_wait_p95_ms"] >= 0
    assert summary["max_queue_size"] == 1
def test_evaluation_separates_recordings_and_reports_exposure():
    from edgevision.evaluation import evaluate_events
    row = {"event_type": "person_entered", "roi_name": "door", "source_time": 1.0}
    scored = evaluate_events([dict(row, source_name="A")], [dict(row, source_name="B")])
    assert (scored["tp"], scored["fp"], scored["fn"]) == (0, 1, 1)
    scored = evaluate_events([dict(row, source_name="A")], [dict(row, source_name="B")],
                             clip_seconds={"A": 3, "B": 5, "empty": 4})
    assert scored["effective_seconds"] == 12
    assert scored["by_event_type"]["person_entered"] == {"truth": 1, "tp": 0, "fp": 1, "fn": 1}
    assert scored["by_event_type"]["person_left"]["truth"] == 0

def test_snapshot_queue_cannot_drop_event_ids(tmp_path, monkeypatch):
    from edgevision.pipeline import Pipeline, _EventOutputWorker
    cfg = config(tmp_path)
    cfg.input.min_sharpness = 0
    monkeypatch.setattr(_EventOutputWorker, "submit", lambda *args: False)
    pipeline = Pipeline(cfg, Frames(), Boxes())
    summary = pipeline.run(mode="sync")
    assert len(pipeline.storage.recent_events()) == summary["events"] == 2
    assert summary["events_persisted"] == 2
    assert summary["events_dropped"] == 0
    assert summary["snapshot_skipped"] == 2

def test_frame_health_reports_processing_failure_and_recovery(tmp_path):
    from edgevision.pipeline import Pipeline
    pipeline = Pipeline(config(tmp_path), Frames(), Boxes(True))
    seen = []
    class Observe(Frames):
        def __iter__(self):
            for frame in super().__iter__():
                seen.append(pipeline.frame_health.status())
                yield frame
    pipeline.source = Observe()
    result = pipeline.run(mode="sync")
    assert seen[1]["state"] == "unavailable"
    assert seen[1]["consecutive_failures"] == 1
    assert seen[2]["state"] == "recovered"
    assert result["frame_health"]["last_success_at"]
    assert result["frame_health"]["consecutive_failures"] == 0

def test_trace_rotates_outside_evidence_directory(tmp_path):
    from edgevision.pipeline import Pipeline
    from edgevision import trace
    import pytest
    path = tmp_path / "diag" / "frames.csv"
    cfg = config(tmp_path / "events")
    with pytest.raises(ValueError, match="event"):
        Pipeline(cfg, Frames(), Boxes()).run(mode="sync", trace_path=cfg.output.directory / "trace.csv")
    original = trace.FrameTrace.MAX_BYTES
    try:
        trace.FrameTrace.MAX_BYTES = 145
        Pipeline(cfg, Frames(), Boxes()).run(mode="sync", trace_path=path)
    finally:
        trace.FrameTrace.MAX_BYTES = original
    files = list(path.parent.glob("frames.csv*"))
    assert len(files) == 2
    assert all(f.stat().st_size <= 145 and f.read_text().startswith("seq,source_time,") for f in files)

def test_camera_health_available_between_frames(tmp_path):
    from edgevision.pipeline import Pipeline
    from edgevision.preview import PreviewServer
    from urllib.request import urlopen
    class Disconnect(Frames):
        on_read_failure = None
        def __iter__(self):
            for frame in super().__iter__():
                if frame.seq == 1:
                    self.on_read_failure("camera_read")
                    self.on_read_failure("camera_read")
                    with urlopen(preview.url + "/status", timeout=2) as response:
                        failed = json.load(response)["frame_health"]
                    assert failed["state"] == "unavailable"
                    assert failed["consecutive_failures"] == 2
                    assert failed["last_success_at"]
                yield frame
    pipeline = Pipeline(config(tmp_path), Disconnect(), Boxes())
    preview = PreviewServer(port=0, frame_health=pipeline.frame_health.status)
    try:
        summary = pipeline.run(mode="sync")
        assert summary["frame_health"]["last_recovery_at"]
    finally:
        preview.close()

def test_slow_old_frame_cannot_clear_newer_camera_failure(tmp_path):
    from edgevision.pipeline import Pipeline
    class LateFrame(Frames):
        on_read_failure = None
        def __iter__(self):
            for frame in super().__iter__():
                frame.captured_at -= 1  # Previously captured frame still in the detector.
                self.on_read_failure("camera_read")
                yield frame
                break
    result = Pipeline(config(tmp_path), LateFrame(), Boxes()).run(mode="sync")
    assert result["frame_health"]["state"] == "unavailable"
    assert result["frame_health"]["consecutive_failures"] == 1

def test_stalled_screenshot_worker_preserves_all_events(tmp_path, monkeypatch):
    import threading
    from edgevision.pipeline import Pipeline
    release = threading.Event()

    class BurstSource(Frames):
        def __iter__(self):
            yield Frame(0, time.monotonic(), np.zeros((100, 100, 3), np.uint8), "burst", 0.)
            release.set()

    class BurstDetector:
        last_inference_ms = 1.
        def detect(self, image):
            return [Detection(i, 10, i + 4, 50, .9) for i in range(40)]

    cfg = config(tmp_path)
    cfg.input.min_sharpness = 0
    cfg.roi.enabled = False
    pipeline = Pipeline(cfg, BurstSource(), BurstDetector())
    original = pipeline.storage.attach_snapshot
    def slow_snapshot(event, image):
        assert release.wait(5)
        return original(event, image)
    monkeypatch.setattr(pipeline.storage, "attach_snapshot", slow_snapshot)
    summary = pipeline.run(mode="sync")
    assert summary["output_queue_dropped"] >= 7
    assert summary["events_dropped"] == 0
    assert summary["events_persisted"] == len(pipeline.storage.recent_events()) == 40
    assert summary["snapshot_saved"] + summary["snapshot_skipped"] == 40

def test_diagnostic_disk_error_does_not_signal_camera_outage(tmp_path, monkeypatch):
    from edgevision.pipeline import Pipeline
    from edgevision.trace import FrameTrace
    def fail(self, row):
        raise OSError("diagnostic volume full")
    monkeypatch.setattr(FrameTrace, "writerow", fail)
    summary = Pipeline(config(tmp_path / "events"), Frames(), Boxes()).run(
        mode="sync", trace_path=tmp_path / "diag" / "frames.csv")
    assert summary["errors"] == 0
    assert summary["events_persisted"] == 2
    assert summary["frame_health"]["state"] == "healthy"
