from datetime import datetime, timezone
import json
import math
from uuid import UUID

import pytest

from edgevision.types import Detection


POLYGON = [(10, 10), (90, 10), (90, 90), (10, 90)]


def track(track_id=1, *, inside=True, timestamp=0.):
    from edgevision.types import Track

    detection = Detection(40, 20, 60, 60, .8) if inside else Detection(100, 20, 120, 60, .7)
    return Track(track_id, detection, timestamp)


def test_first_inside_observation_emits_a_serializable_utc_enter_event():
    from edgevision.events import EventEngine

    engine = EventEngine("door", POLYGON)
    event, = engine.update([track()], 0., "clip", source_time=12.3)
    assert event.event_type == "person_entered"
    assert event.roi_name == "door"
    assert event.track_id == 1
    assert event.confidence == .8
    assert event.source_name == "clip"
    assert event.source_time == 12.3
    assert event.bbox == (40, 20, 60, 60)
    assert UUID(event.event_id)
    occurred = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00"))
    assert occurred.utcoffset().total_seconds() == 0
    assert abs((datetime.now(timezone.utc) - occurred).total_seconds()) < 2
    payload = event.to_dict()
    assert payload["schema_version"] == 1
    assert payload["bbox"] == [40, 20, 60, 60]
    assert json.loads(json.dumps(payload))["event_id"] == event.event_id


def test_live_source_can_omit_file_position_from_the_event():
    from edgevision.events import EventEngine

    event, = EventEngine("door", POLYGON).update([track()], 0., "camera", source_time=None)
    assert event.to_dict()["source_time"] is None


def test_enter_and_leave_follow_bottom_center_transitions():
    from edgevision.events import EventEngine

    engine = EventEngine("door", POLYGON, cooldown_seconds=0.)
    assert engine.update([track(inside=False)], 0., "clip") == []
    assert [event.event_type for event in engine.update([track()], 1., "clip")] == ["person_entered"]
    assert engine.update([track()], 2., "clip") == []
    assert [event.event_type for event in engine.update([track(inside=False)], 3., "clip")] == ["person_left"]
    assert engine.update([track(inside=False)], 4., "clip") == []


def test_boundary_bottom_center_counts_as_inside_even_if_box_extends_outside():
    from edgevision.events import EventEngine
    from edgevision.types import Track

    engine = EventEngine("door", POLYGON)
    observation = Track(1, Detection(0, 0, 20, 10, .9), 0.)
    assert len(engine.update([observation], 0., "clip")) == 1


def test_cooldown_applies_to_reentry_per_track_and_does_not_repeat_while_inside():
    from edgevision.events import EventEngine

    engine = EventEngine("door", POLYGON, cooldown_seconds=5., emit_leave=False)
    assert len(engine.update([track()], 0., "clip")) == 1
    assert engine.update([track(inside=False)], 1., "clip") == []
    assert engine.update([track()], 2., "clip") == []
    assert engine.update([track()], 6., "clip") == []
    assert engine.update([track(inside=False)], 7., "clip") == []
    events = engine.update([track(), track(2)], 8., "clip")
    assert [event.track_id for event in events] == [1, 2]
    assert len({event.event_id for event in events}) == 2


def test_brief_missing_detection_neither_emits_leave_nor_duplicates_entry():
    from edgevision.events import EventEngine

    engine = EventEngine("door", POLYGON)
    assert len(engine.update([track()], 0., "clip")) == 1
    assert engine.update([], 1., "clip") == []
    assert engine.update([track()], 2., "clip") == []


def test_event_history_expires_without_synthesizing_missing_track_leave():
    from edgevision.events import EventEngine

    engine = EventEngine("door", POLYGON, cooldown_seconds=0., state_timeout_seconds=2.)
    for index in range(100):
        engine.update([track(index)], float(index), "clip")
        assert engine.state_count <= 3
    assert engine.update([], 102., "clip") == []
    assert engine.state_count == 0
    assert len(engine.update([track(99)], 103., "clip")) == 1


def test_cooldown_survives_shorter_state_timeout():
    from edgevision.events import EventEngine

    engine = EventEngine("door", POLYGON, cooldown_seconds=10., state_timeout_seconds=1., emit_leave=False)
    engine.update([track()], 0., "clip")
    engine.update([track(inside=False)], 1., "clip")
    engine.update([], 3., "clip")
    assert engine.update([track()], 4., "clip") == []


@pytest.mark.parametrize("options", [{"cooldown_seconds": -1}, {"cooldown_seconds": math.nan}, {"state_timeout_seconds": 0}, {"state_timeout_seconds": math.inf}])
def test_event_engine_rejects_invalid_durations(options):
    from edgevision.events import EventEngine

    with pytest.raises(ValueError):
        EventEngine("door", POLYGON, **options)


def test_event_engine_rejects_invalid_polygon_during_configuration():
    from edgevision.events import EventEngine

    with pytest.raises(ValueError):
        EventEngine("door", [(0, 0), (1, 1), (2, 2)])


@pytest.mark.parametrize("timestamp", [-1., math.nan, math.inf])
def test_event_engine_rejects_nonfinite_or_decreasing_timestamp(timestamp):
    from edgevision.events import EventEngine

    engine = EventEngine("door", POLYGON)
    engine.update([], 0., "clip")
    with pytest.raises(ValueError):
        engine.update([], timestamp, "clip")

def test_diagnostics_explain_actual_entry_stay_exit_and_cooldown():
    from edgevision.events import EventEngine
    engine = EventEngine("door", POLYGON, cooldown_seconds=5.)
    engine.update([track(inside=False)], 0.)
    assert engine.diagnostics[0]["reason"] == "outside_roi"
    assert engine.diagnostics[0]["inside"] is False
    assert len(engine.update([track()], 1.)) == 1
    assert engine.diagnostics[0]["reason"] == "entered"
    engine.update([track()], 2.)
    assert engine.diagnostics[0]["reason"] == "already_inside"
    assert engine.diagnostics[0]["point"] == [50., 60.]
    engine.update([track(inside=False)], 3.)
    assert engine.diagnostics[0]["reason"] == "left"
    assert engine.update([track()], 4.) == []
    assert engine.diagnostics[0]["reason"] == "cooldown"
    assert engine.diagnostics[0]["cooldown_remaining"] == 2.
    assert engine.update([track()], 7.) == []
    assert engine.diagnostics[0]["reason"] == "inside_suppressed"
    engine.update([], 8.)
    assert engine.diagnostics == []

def test_bottom_clipped_box_has_no_entry_when_point_is_below_roi():
    from edgevision.events import EventEngine
    from edgevision.types import Track
    engine = EventEngine("door", [(0, 0), (640, 0), (640, 456), (0, 456)])
    observation = Track(1, Detection(280,90,420,480,.9), 0.)
    assert engine.update([observation], 0.) == []
    assert engine.diagnostics[0]["inside"] is False
    assert engine.diagnostics[0]["point"] == [350., 480.]
