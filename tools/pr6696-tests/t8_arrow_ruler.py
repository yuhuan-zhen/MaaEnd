#!/usr/bin/env python3
"""T8 · 朝向读取器的离线验证（用 MaaEndTestset 的带标注截图）

数据：`MaaEndTestset/Win32/Official_CN/map_tracker/*_r{N}.png`，文件名末尾是真值朝向。
用途三种：

  1. 回归：改了读取器就重跑，确认没有退化
        python3 t8_arrow_ruler.py --dir <testset>/Win32/Official_CN/map_tracker
  2. 单帧：印一张图的读数（可用于确认云网页 HUD 与 Win32 是否一致）
        python3 t8_arrow_ruler.py --frame trial-A.png
  3. ROI 扫描：圆心/尺寸不确定时，找误差最小的组合
        python3 t8_arrow_ruler.py --dir <…> --sweep-roi

判据（86 张基准）：成功 86/86、中位 ≤2°、最大 ≤10°、系统性偏差 ≤1°。
"""

from __future__ import annotations

import argparse
import pathlib
import re
import statistics
import sys

import cv2

import arrow_ruler as ruler

TRUTH = re.compile(r"_r(\d+)\.png$")


def evaluate(directory: pathlib.Path, roi: tuple[int, int, int, int], verbose: bool) -> tuple[list[float], list[str], list[tuple]]:
    x, y, w, h = roi
    errors: list[float] = []
    failures: list[str] = []
    rows: list[tuple] = []
    for path in sorted(directory.glob("*.png")):
        match = TRUTH.search(path.name)
        if not match:
            continue
        frame = cv2.imread(str(path))
        if frame is None:
            failures.append(path.name)
            continue
        patch = frame[y:y + h, x:x + w]
        angle = ruler.infer_arrow_angle(patch)
        if angle < 0:
            failures.append(path.name)
            continue
        truth = float(match.group(1))
        error = ruler.circular_delta(truth, angle)
        errors.append(error)
        rows.append((path.name, truth, angle, error))
        if verbose:
            print(f"  {path.name[:50]:<50} 真值 {truth:5.0f}° 读数 {angle:6.1f}° 差 {error:+6.1f}°")
    return errors, failures, rows


def report(errors: list[float], failures: list[str], rows: list[tuple]) -> None:
    absolute = [abs(e) for e in errors]
    print(f"成功 {len(errors)} / 失败 {len(failures)}")
    if not errors:
        return
    print(f"误差：中位 {statistics.median(absolute):.2f}°  "
          f"均值 {statistics.fmean(absolute):.2f}°  最大 {max(absolute):.2f}°")
    print(f"系统性偏差中位 {statistics.median(errors):+.2f}°")
    for limit in (2, 5, 10):
        count = sum(1 for e in absolute if e <= limit)
        print(f"  ≤{limit}°: {count}/{len(errors)} ({count * 100 // len(errors)}%)")
    worst = sorted(rows, key=lambda r: -abs(r[3]))[:5]
    print("最差 5 个：")
    for name, truth, angle, error in worst:
        print(f"  {name[:50]:<50} 真值 {truth:5.0f}° 读数 {angle:6.1f}° 差 {error:+6.1f}°")


def main() -> int:
    parser = argparse.ArgumentParser(description="朝向读取器离线验证")
    parser.add_argument("--dir", help="含 *_r{N}.png 的目录")
    parser.add_argument("--frame", help="单帧图片（全屏 1280×720）")
    parser.add_argument("--sweep-roi", action="store_true", help="扫描 ROI 找最小误差")
    parser.add_argument("--roi", default=f"{ruler.ROI_X},{ruler.ROI_Y},{ruler.ROI_W},{ruler.ROI_H}")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.frame:
        frame = cv2.imread(args.frame)
        if frame is None:
            raise SystemExit(f"读不到 {args.frame}")
        angle = ruler.angle_of_frame(frame)
        print(f"{args.frame}: {angle:6.1f}°" if angle >= 0 else f"{args.frame}: 读不出（-1）")
        return 0 if angle >= 0 else 1

    if not args.dir:
        raise SystemExit("需要 --dir 或 --frame")
    directory = pathlib.Path(args.dir)

    if args.sweep_roi:
        print("ROI 扫描（前 12 名）")
        results = []
        for cx in range(100, 118):
            for cy in range(102, 120):
                for half in (26, 28, 30, 32):
                    roi = (cx - half // 2 - 8, cy - half // 2 - 8, half * 2 + 16, half * 2 + 16)
                    errors, failures, _ = evaluate(directory, roi, verbose=False)
                    if len(errors) < 80:
                        continue
                    results.append((statistics.median([abs(e) for e in errors]), roi, len(failures)))
        results.sort()
        for median_error, roi, failures in results[:12]:
            print(f"  中位 {median_error:5.2f}°  失败 {failures:2d}  ROI={roi}")
        return 0

    roi = tuple(int(v) for v in args.roi.split(","))
    errors, failures, rows = evaluate(directory, roi, args.verbose)
    print(f"目录 {directory}  ROI={roi}")
    report(errors, failures, rows)
    if failures:
        print(f"失败样本（前 5）：{failures[:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
