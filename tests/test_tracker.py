import math

import pytest

from edgevision.types import Detection


def d(x1, y1, x2, y2, confidence=.9):
    return Detection(x1, y1, x2, y2, confidence)


def test_tracker_assigns_stable_ids_and_returns_observed_tracks_only():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker(max_age_frames=2, iou_threshold=.1, max_centroid_distance=.5)
    first = tracker.update([d(0, 0, 10, 10), d(100, 0, 110, 10)], 0.0, (100, 120))
    assert [track.track_id for track in first] == [1, 2]
    second = tracker.update([d(101, 0, 111, 10)], 1.0, (100, 120))
    assert [track.track_id for track in second] == [2]
    assert second[0].missed == 0


def test_tracker_is_one_to_one_and_uses_iou_distance_to_avoid_id_swap():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker(max_age_frames=3, iou_threshold=.05, max_centroid_distance=.8)
    tracks = tracker.update([d(0, 0, 10, 10), d(40, 0, 50, 10)], 0.0, (100, 100))
    assert len({track.track_id for track in tracks}) == 2
    updated = tracker.update([d(2, 0, 12, 10), d(38, 0, 48, 10)], 1.0, (100, 100))
    assert [track.track_id for track in updated] == [1, 2]
    assert updated[0].detection.x1 == 2
    assert updated[1].detection.x1 == 38


def test_tracker_does_not_match_far_or_low_iou_detections():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker(max_age_frames=2, iou_threshold=.2, max_centroid_distance=.1)
    first = tracker.update([d(0, 0, 10, 10)], 0.0, (100, 100))
    second = tracker.update([d(80, 80, 90, 90)], 1.0, (100, 100))
    assert second[0].track_id != first[0].track_id
    assert second[0].track_id == 2


def test_tracker_expires_missed_tracks_and_reclaims_history():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker(max_age_frames=2)
    first = tracker.update([d(0, 0, 10, 10)], 0.0, (100, 100))[0]
    assert tracker.update([], 1.0, (100, 100)) == []
    assert tracker.update([], 2.0, (100, 100)) == []
    assert tracker.update([], 3.0, (100, 100)) == []
    replacement = tracker.update([d(0, 0, 10, 10)], 4.0, (100, 100))[0]
    assert replacement.track_id != first.track_id


@pytest.mark.parametrize("image_shape", [(0, 1), (-1, 100), (100,), (math.inf, 100)])
def test_tracker_rejects_invalid_image_dimensions(image_shape):
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker()
    with pytest.raises(ValueError):
        tracker.update([d(0, 0, 1, 1)], 0.0, image_shape)


def test_tracker_reuses_track_after_a_brief_missing_observation():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker(max_age_frames=2)
    first = tracker.update([d(0, 0, 10, 10)], 0., (100, 100))[0]
    tracker.update([], 1., (100, 100))
    assert tracker.active_tracks[0].missed == 1
    recovered = tracker.update([d(1, 0, 11, 10)], 2., (100, 100))[0]
    assert recovered.track_id == first.track_id
    assert recovered.last_seen == 2.
    assert recovered.missed == 0


def test_normalized_centroid_distance_can_match_small_nonoverlapping_movement():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker(max_centroid_distance=.15)
    first = tracker.update([d(0, 0, 10, 10)], 0., (100, 100))[0]
    second = tracker.update([d(11, 0, 21, 10)], 1., (100, 100))[0]
    assert second.track_id == first.track_id


def test_one_existing_track_cannot_absorb_two_detections():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker()
    tracker.update([d(0, 0, 10, 10)], 0., (100, 100))
    tracks = tracker.update([d(0, 0, 10, 10), d(1, 0, 11, 10)], 1., (100, 100))
    assert [track.track_id for track in tracks] == [1, 2]


def test_tracker_history_is_bounded_by_the_recent_frame_window():
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker(max_age_frames=2, max_centroid_distance=0., iou_threshold=1.)
    for index in range(100):
        tracker.update([d(index * 20, 0, index * 20 + 10, 10)], float(index), (100, 10000))
        assert len(tracker.active_tracks) <= 3
    tracker.update([], 100., (100, 10000))
    tracker.update([], 101., (100, 10000))
    tracker.update([], 102., (100, 10000))
    assert tracker.active_tracks == ()


@pytest.mark.parametrize("options", [{"max_age_frames": -1}, {"max_age_frames": 1.5}, {"iou_threshold": -1}, {"iou_threshold": 1.1}, {"max_centroid_distance": -1}, {"max_centroid_distance": math.nan}])
def test_tracker_rejects_invalid_configuration(options):
    from edgevision.tracker import CentroidIoUTracker

    with pytest.raises(ValueError):
        CentroidIoUTracker(**options)


@pytest.mark.parametrize("timestamp", [-1., math.nan, math.inf])
def test_tracker_rejects_nonfinite_or_decreasing_timestamp(timestamp):
    from edgevision.tracker import CentroidIoUTracker

    tracker = CentroidIoUTracker()
    tracker.update([], 0., (100, 100))
    with pytest.raises(ValueError):
        tracker.update([], timestamp, (100, 100))
