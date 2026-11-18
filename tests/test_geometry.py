"""Behavior of the shared value objects and pixel geometry."""

from dataclasses import FrozenInstanceError
import math

import pytest


def test_bottom_center_uses_the_feet_of_the_detection():
    from edgevision.geometry import bottom_center

    assert bottom_center((10, 20, 30, 60)) == (20, 60)


@pytest.mark.parametrize("point", [(0, 0), (10, 5), (5, 10), (5, 5)])
def test_polygon_includes_its_edges_and_vertices(point):
    from edgevision.geometry import point_in_polygon

    assert point_in_polygon(point, [(0, 0), (10, 0), (10, 10), (0, 10)])


def test_polygon_respects_concave_cutout_and_vertex_order():
    from edgevision.geometry import point_in_polygon

    polygon = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
    assert point_in_polygon((0.5, 3), polygon)
    assert not point_in_polygon((3, 3), polygon)
    assert point_in_polygon((0.5, 3), list(reversed(polygon)))
    assert not point_in_polygon((-0.01, 1), polygon)


@pytest.mark.parametrize("polygon", [[], [(0, 0), (1, 1)], [(0, 0), (1, 1), (2, 2)], [(0, 0), (1, 0), (math.nan, 1)]])
def test_polygon_rejects_degenerate_or_nonfinite_input(polygon):
    from edgevision.geometry import point_in_polygon

    with pytest.raises(ValueError):
        point_in_polygon((0, 0), polygon)


def test_polygon_rejects_nonfinite_point():
    from edgevision.geometry import point_in_polygon

    with pytest.raises(ValueError):
        point_in_polygon((math.inf, 0), [(0, 0), (1, 0), (0, 1)])


def test_iou_handles_overlap_disjoint_and_zero_area_boxes():
    from edgevision.geometry import iou

    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0
    assert iou((0, 0, 0, 10), (0, 0, 10, 10)) == 0


@pytest.mark.parametrize("bbox", [(1, 0, 0, 1), (0, 1, 1, 0), (0, 0, math.inf, 1), (0, 0, 1)])
def test_geometry_rejects_invalid_bounding_boxes(bbox):
    from edgevision.geometry import bottom_center, iou

    with pytest.raises(ValueError):
        bottom_center(bbox)
    with pytest.raises(ValueError):
        iou(bbox, (0, 0, 1, 1))


def test_detection_is_immutable_and_exposes_bbox():
    from edgevision.types import Detection

    detection = Detection(1, 2, 3, 4, 0.7)
    assert detection.bbox == (1, 2, 3, 4)
    assert detection.class_name == "person"
    with pytest.raises(FrozenInstanceError):
        detection.x1 = 10


@pytest.mark.parametrize("args", [(0, 0, 0, 1, .9), (1, 0, 0, 1, .9), (0, 0, 1, 1, -0.1), (0, 0, 1, 1, 1.1), (0, 0, math.nan, 1, .9)])
def test_detection_rejects_invalid_values(args):
    from edgevision.types import Detection

    with pytest.raises(ValueError):
        Detection(*args)


def test_frame_keeps_monotonic_capture_time_separate_from_file_time():
    from edgevision.types import Frame

    image = object()
    frame = Frame(7, 123.4, image, "clip", source_time=3.2)
    assert frame.seq == 7
    assert frame.captured_at == 123.4
    assert frame.source_time == 3.2
    assert frame.image is image
