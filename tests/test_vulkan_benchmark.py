from pathlib import Path
import runpy

import pytest


@pytest.fixture(scope="module")
def benchmark():
    return runpy.run_path(str(Path(__file__).parents[1] / "benchmarks/compare_vulkan.py"))


def test_focus_rewrite_preserves_yolox_channel_order(benchmark):
    graph = """7767517
8 11
Input in0 0 1 in0
Split splitncnn_0 1 4 in0 1 2 3 4
Tensor.slice Tensor.slice_23 1 1 4 5
Tensor.slice Tensor.slice_25 1 1 3 6
Tensor.slice Tensor.slice_27 1 1 2 7
Tensor.slice Tensor.slice_29 1 1 1 8
Concat cat_0 4 1 5 7 6 8 9 0=0
Convolution conv_115 1 1 9 out0
"""
    rewrite = benchmark["rewrite_focus"]
    converted = rewrite(graph).splitlines()
    assert converted[1] == "5 8"
    assert converted[3:] == [
        "Reorg focus_reorg 1 1 in0 1 0=2 1=1",
        "Slice focus_split 1 4 1 2 3 4 5 -23300=4,3,3,3,3 1=0",
        "Concat focus_concat 4 1 2 4 3 5 9 0=0",
        "Convolution conv_115 1 1 9 out0",
    ]
    with pytest.raises(ValueError, match="Focus"):
        rewrite(graph.replace("5 7 6 8", "5 6 7 8"))


def test_comparison_counts_each_detection_at_most_once(benchmark):
    from edgevision.types import Detection

    base = Detection(0, 0, 10, 10, .75)
    duplicate = Detection(0, 0, 10, 10, .50)
    far = Detection(20, 0, 30, 10, .75)
    result = benchmark["compare_detections"]([[base], [far]], [[duplicate, base], []])
    assert result["matched_boxes"] == 1
    assert result["unmatched_reference_boxes"] == 1
    assert result["unmatched_candidate_boxes"] == 1
    assert result["minimum_matched_iou"] == 1.0
