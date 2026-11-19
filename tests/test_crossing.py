from edgevision.events import EventEngine
from edgevision.types import Detection, Track


def test_only_confirmed_crossings_emit_events():
    engine = EventEngine("door", [(0, 0), (100, 0), (100, 100), (0, 100)])
    def observe(i, foot=None, score=.8):
        tracks = [] if foot is None else [Track(1, Detection(20, 20, 40, foot, score), i)]
        return [event.event_type for event in engine.update(tracks, i / 25)]
    assert observe(0, 80) == []
    assert observe(1, 80) == []
    assert observe(2, 100.3) == []
    assert observe(3, 110) == []
    assert observe(4) == []
    assert observe(5, 110) == []
    assert observe(6, 110) == ["person_left"]
    assert observe(7, 80) == []
    assert observe(8, 80, .39) == []
    assert observe(9, 80, .59) == []
    assert observe(10, 80, .70) == ["person_entered"]
