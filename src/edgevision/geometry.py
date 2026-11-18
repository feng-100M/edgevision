"""不依赖第三方库的边界框和多边形运算，统一使用像素坐标。

配置文件中的 ROI 点是 ``0..1`` 的归一化坐标，流水线在拿到图像尺寸后
才把它们转换成像素坐标；这样几何函数可以独立测试，也不会混淆两种坐标系。

这里的函数只回答几何问题，不知道帧来自视频还是摄像头。流水线负责把归一化
ROI 转成像素多边形，再把检测框的底部中心交给本模块判断，这样坐标约定只有一个入口。
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _coordinates(values: Sequence[float], size: int) -> tuple[float, ...]:
    # 所有公开几何运算先经过同一套长度和有限值检查，避免不同函数产生不一致的边界行为。
    if len(values) != size:
        raise ValueError(f"Expected {size} coordinates")
    result = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in result):
        raise ValueError("Coordinates must be finite")
    return result


def _bbox(bbox: Sequence[float]) -> tuple[float, ...]:
    # 允许零面积框留给 IoU 返回 0，但禁止角点顺序颠倒，因为那通常表示上游坐标错误。
    coordinates = _coordinates(bbox, 4)
    if coordinates[2] < coordinates[0] or coordinates[3] < coordinates[1]:
        raise ValueError("Bounding box corners are reversed")
    return coordinates


def bottom_center(bbox: Sequence[float]) -> tuple[float, float]:
    """返回用于判断人员脚部是否进入 ROI 的框底部中心点。"""
    # 用脚部近似人的落地点，比用整个框或框中心更符合“人是否进入区域”的业务语义。
    x1, _, x2, y2 = _bbox(bbox)
    return ((x1 + x2) / 2, y2)


def point_in_polygon(point: Sequence[float],
                     polygon: Sequence[Sequence[float]]) -> bool:
    """使用射线法判断点是否在多边形内，并把边界算作内部。"""
    x, y = _coordinates(point, 2)
    vertices = [_coordinates(vertex, 2) for vertex in polygon]
    if len(vertices) < 3:
        raise ValueError("A polygon needs at least three vertices")
    # 将最后一个顶点和第一个顶点闭合，后续既检查边界，也统计射线穿越次数。
    edges = list(zip(vertices, vertices[1:] + vertices[:1]))
    twice_area = sum(ax * by - bx * ay for (ax, ay), (bx, by) in edges)
    if abs(twice_area) <= 1e-12:
        raise ValueError("Polygon must enclose a nonzero area")

    # 先单独判定点是否落在边上；边界算内部，避免 ROI 边缘抖动造成状态来回切换。
    inside = False
    for (ax, ay), (bx, by) in edges:
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        tolerance = 1e-9 * max(1.0, abs(bx - ax), abs(by - ay))
        if abs(cross) <= tolerance and min(ax, bx) - 1e-9 <= x <= max(ax,
                                                                      bx) + 1e-9 and min(ay, by) - 1e-9 <= y <= max(ay, by) + 1e-9:
            return True
        # 对跨过水平射线的边计数，奇数次代表点在多边形内部。
        if (ay > y) != (by > y):
            crossing_x = ax + (y - ay) * (bx - ax) / (by - ay)
            if x < crossing_x:
                inside = not inside
    return inside


def iou(first: Sequence[float], second: Sequence[float]) -> float:
    """计算交并比；零面积框没有重叠面积。"""
    # IoU 同时用于 NMS 和跟踪匹配；统一在这里计算可以保证两处对重叠的定义一致。
    ax1, ay1, ax2, ay2 = _bbox(first)
    bx1, by1, bx2, by2 = _bbox(second)
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * \
        max(0.0, min(ay2, by2) - max(ay1, by1))
    union = (ax2 - ax1) * (ay2 - ay1) + \
        (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0
