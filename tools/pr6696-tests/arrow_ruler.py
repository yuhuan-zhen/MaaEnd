#!/usr/bin/env python3
"""朝向读取器：MaaEnd `InferYellowArrowRotation` 的 Python 移植 + 小地图 ROI 常量。

移植来源：`agent/cpp-algo/source/MapLocator/MapAlgorithm.cpp:95-279`
ROI 来源：`agent/cpp-algo/source/MapLocator/MapTypes.h:139`
          `constexpr MinimapRoiConfig kDefaultMinimapRoi { 49, 51, 118, 120 };`

已验证：MaaEndTestset 的 86 张 `Win32/Official_CN/map_tracker/*_r{N}.png`
        → 86/86 读出，中位误差 1.41°，最大 7.30°（见 t8_arrow_ruler.py）

语义：读到的是 **`rot`（角色朝向）**，不是 `camRot`（镜头朝向）。
      `docs/zh_cn/developers/components/map-locator.md:41-43` 明确两者无关联。
      0° = 正北（画面上方），顺时针为正。
"""
from __future__ import annotations

import math

import cv2
import numpy as np

ROI_X, ROI_Y, ROI_W, ROI_H = 49, 51, 118, 120
CENTER = (ROI_X + ROI_W // 2, ROI_Y + ROI_H // 2)   # (108, 111)
PATCH_RADIUS = 12                                    # 上游只取中心 24×24


def crop_minimap(frame: np.ndarray) -> np.ndarray:
    return frame[ROI_Y:ROI_Y + ROI_H, ROI_X:ROI_X + ROI_W]


def infer_arrow_angle(minimap_bgr: np.ndarray) -> float:
    """返回箭头角度（度，0=上，顺时针）。读不出返回 -1.0。"""
    if minimap_bgr.size == 0:
        return -1.0
    height, width = minimap_bgr.shape[:2]
    cx, cy = width // 2, height // 2
    radius = PATCH_RADIUS
    if cx - radius < 0 or cy - radius < 0 or cx + radius > width or cy + radius > height:
        return -1.0

    patch = minimap_bgr[cy - radius:cy + radius, cx - radius:cx + radius]
    white = cv2.inRange(patch, (220, 220, 220), (255, 255, 255))
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return -1.0

    # 取质心离中心最近的轮廓；> 5px 视为噪点
    center = np.array([radius, radius], dtype=np.float64)
    best_index, best_dist_sq = -1, 1e9
    for index, contour in enumerate(contours):
        moments = cv2.moments(contour)
        if moments["m00"] > 0:
            centroid = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]])
        else:
            centroid = contour[0][0].astype(np.float64)
        dist_sq = float(((centroid - center) ** 2).sum())
        if dist_sq < best_dist_sq:
            best_dist_sq, best_index = dist_sq, index
    if best_index < 0 or best_dist_sq > 25.0:
        return -1.0

    isolated = np.zeros(white.shape, np.uint8)
    cv2.drawContours(isolated, contours, best_index, 255, cv2.FILLED)
    high = cv2.resize(isolated, None, fx=16.0, fy=16.0, interpolation=cv2.INTER_CUBIC)
    _, high = cv2.threshold(high, 127, 255, cv2.THRESH_BINARY)
    high_contours, _ = cv2.findContours(high, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not high_contours:
        return -1.0

    largest = max(high_contours, key=cv2.contourArea)
    moments = cv2.moments(largest)
    if moments["m00"] <= 0:
        return -1.0
    centroid = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]])

    _, triangle = cv2.minEnclosingTriangle(largest)
    if triangle is None or len(triangle) != 3:
        return -1.0
    triangle = triangle.reshape(-1, 2)

    forward = _arrow_forward(largest, centroid)
    if forward is not None:
        dots = []
        for vertex in triangle:
            delta = vertex - centroid
            norm = float(np.linalg.norm(delta))
            dots.append(-1.0 if norm < 1e-9 else float(np.dot(delta, forward)) / norm)
        tip = triangle[int(np.argmax(dots))]
    else:
        distances = [float(np.linalg.norm(vertex - centroid)) for vertex in triangle]
        tip = triangle[int(np.argmax(distances))]

    dx, dy = float(tip[0] - centroid[0]), float(tip[1] - centroid[1])
    angle = math.degrees(math.atan2(dx, -dy))
    return angle + 360.0 if angle < 0 else angle


def _arrow_forward(contour: np.ndarray, centroid: np.ndarray) -> np.ndarray | None:
    """上游 `EstimateArrowForward`：凸包 → 逼近成三角形 → 最尖的角作为朝向。"""
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    corners = None
    for eps in (0.05, 0.04, 0.06, 0.03, 0.08, 0.02, 0.10):
        approx = cv2.approxPolyDP(hull, eps * perimeter, True)
        if len(approx) == 3:
            corners = approx
            break
    if corners is None:
        return None

    sharpest, max_cos = -1, -2.0
    for i in range(3):
        v1 = corners[(i + 2) % 3][0] - corners[i][0]
        v2 = corners[(i + 1) % 3][0] - corners[i][0]
        norm = math.hypot(float(v1[0]), float(v1[1])) * math.hypot(float(v2[0]), float(v2[1]))
        cos = -1.0 if norm < 1e-9 else float(np.dot(v1, v2)) / norm
        if cos > max_cos:
            max_cos, sharpest = cos, i
    if sharpest < 0:
        return None
    forward = corners[sharpest][0].astype(np.float64) - centroid
    norm = float(np.linalg.norm(forward))
    return None if norm < 1e-6 else forward / norm


def angle_of_frame(frame: np.ndarray) -> float:
    return infer_arrow_angle(crop_minimap(frame))


def circular_delta(before: float, after: float) -> float:
    """after - before，归一化到 (-180, 180]。"""
    return (after - before + 540.0) % 360.0 - 180.0
