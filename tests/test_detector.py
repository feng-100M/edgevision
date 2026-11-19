import numpy as np
import pytest

def test_preprocess_preserves_bgr_and_pixel_scale():
    from edgevision.detector import preprocess
    image = np.full((100,200,3), [10,20,30], dtype=np.uint8)
    tensor, ratio = preprocess(image, (416,416))
    assert ratio == 2.08
    assert tensor.shape == (1,3,416,416)
    assert tensor[0,:,0,0].tolist() == [10,20,30]
    assert tensor[0,:,300,0].tolist() == [114,114,114]

def test_yolox_raw_grid_decode_and_nms():
    from edgevision.detector import postprocess
    raw = np.zeros((1,3549,85), dtype=np.float32)
    # stride 8 anchors produce same 8x8 box at (4,4) after decoding.
    raw[0,0,:6] = [.5,.5,0,0,.9,.9]
    raw[0,1,:6] = [-.5,.5,0,0,.8,.9]
    raw[0,2,4] = .9; raw[0,2,6] = .95  # class bicycle, not person
    boxes = postprocess(raw, (416,416), (416,416), 1., .35, .45)
    assert len(boxes) == 1
    assert boxes[0].bbox == (0.,0.,8.,8.)
    assert boxes[0].confidence == pytest.approx(.81)

def test_missing_model_fails_with_path(tmp_path):
    from edgevision.detector import Detector, DetectorError
    with pytest.raises(DetectorError, match="missing.onnx"):
        Detector(tmp_path / "missing.onnx")

def test_malformed_model_output_rejected():
    from edgevision.detector import postprocess, DetectorError
    with pytest.raises(DetectorError):
        postprocess(np.zeros((1,1,85)), (416,416), (416,416), 1., .35, .45)

def test_person_candidate_is_rejected_when_another_class_scores_higher():
    from edgevision.detector import postprocess
    raw = np.zeros((1,3549,85), dtype=np.float32)
    raw[0,0,:6] = [.5,.5,0,0,.9,.6]
    raw[0,0,6] = .95
    assert postprocess(raw, (416,416), (416,416), 1.) == []

def test_person_candidate_survives_lower_competing_class_score():
    from edgevision.detector import postprocess
    raw = np.zeros((1,3549,85), dtype=np.float32)
    raw[0,0,:6] = [.5,.5,0,0,.9,.9]
    raw[0,0,6] = .6
    assert len(postprocess(raw, (416,416), (416,416), 1.)) == 1


def test_class_scan_only_visits_candidates_above_threshold(monkeypatch):
    from edgevision.detector import postprocess
    raw = np.zeros((1, 2100, 85), dtype=np.float32)
    raw[0, 1, :6] = [.5, .5, 0, 0, .9, .9]
    original = np.argmax
    visited = []
    def count_rows(values, axis):
        visited.append(values.shape[0])
        return original(values, axis=axis)
    monkeypatch.setattr(np, "argmax", count_rows)
    assert len(postprocess(raw, (320, 320), (320, 320), 1.)) == 1
    assert visited == [1]


@pytest.mark.parametrize("angle,box", [
    (0, (10, 20, 30, 40)), (90, (20, 50, 40, 70)),
    (180, (90, 40, 110, 60)), (270, (80, 10, 100, 30)),
])
def test_assisted_box_maps_to_original_nonsquare_image(angle, box):
    from edgevision.detector import restore_detection
    from edgevision.types import Detection

    output = restore_detection(Detection(10, 20, 30, 40, .72), angle, (80, 120, 3))
    assert output.bbox == box
    assert output.confidence == .72
