#!/usr/bin/env python3
"""T1 · 取帧延迟与编码代价（验证 #6696 的取帧断言）

#6696 断言：从网页 <video> 取帧经 CDP 回传可用，实测 1080p JPEG 约 190 ms/帧。
本脚本要回答的四个问题：

1. 在同一页面、同一浏览器会话下，四条取帧路径各要多久
2. 每帧 base64 有多少字节（这比毫秒更能说明瓶颈：字节数 × fps = 需要多少带宽）
3. 改成 JPEG 后省多少，代价是什么
4. 1080p 相对 720p 的缩放关系（用来核对 190 ms 这个数）

四条路径：
  P1  Page.captureScreenshot            PNG，全视口
  P2  Runtime.evaluate toDataURL        image/png
  P3  Runtime.evaluate toDataURL        image/jpeg, 质量 1.0 / 0.9 / 0.8
  P4  Page.captureScreenshot            format=jpeg, 同质量

用法：
  python3 t1_frame_latency.py --image ../linux-adapt/evidence-l1/f2-red.png
  python3 t1_frame_latency.py --frames 30 --batches 3 --sizes 1280x720,1920x1080
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import tempfile
import time

import _common as c


def find_image(explicit: str | None) -> pathlib.Path:
    if explicit:
        path = pathlib.Path(explicit)
        if not path.exists():
            raise SystemExit(f"素材不存在：{path}")
        return path
    here = pathlib.Path(__file__).resolve().parent
    for candidate in (
        here.parent / "linux-adapt" / "evidence-l1" / "f2-red.png",
        here.parent / "linux-adapt" / "evidence-l1" / "f1-dark.png",
    ):
        if candidate.exists():
            return candidate
    raise SystemExit("找不到帧素材，请用 --image 指定一张真实截图（不要用纯色图）")


def compression_ratio(path: pathlib.Path) -> float | None:
    """原始像素 / PNG 体积。纯色图这个比值会极大（几百），真实游戏帧通常在个位数到几十。"""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 33:
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if not width or not height:
        return None
    return (width * height * 3) / max(len(data), 1)


def prepare_site(image: pathlib.Path) -> tuple[pathlib.Path, bool]:
    here = pathlib.Path(__file__).resolve().parent
    site = pathlib.Path(tempfile.mkdtemp(prefix="t1-site-"))
    shutil.copy(here / "probe" / "index.html", site / "index.html")
    shutil.copy(image, site / "frame.png")
    return site, False


def measure_once(cdp: c.Cdp, frames: int, warmup: int, width: int, height: int, jpeg_qualities: list[float]) -> dict:
    """跑一轮：每条路径 frames 次，丢掉前 warmup 个。"""
    cdp.call("Emulation.setDeviceMetricsOverride",
             width=width, height=height, deviceScaleFactor=1,
             screenWidth=width, screenHeight=height, mobile=False)

    samples: dict[str, list[float]] = {}
    sizes: dict[str, list[int]] = {}

    def timed(key: str, fn) -> None:
        start = time.perf_counter()
        payload = fn()
        elapsed = (time.perf_counter() - start) * 1000.0
        samples.setdefault(key, []).append(elapsed)
        if isinstance(payload, str):
            # data URL（含 "data:...,"前缀）或纯 base64 都要能算原始字节数
            encoded = payload.split(",", 1)[1] if "," in payload else payload
            sizes.setdefault(key, []).append(len(encoded) * 3 // 4)

    for _ in range(frames + warmup):
        timed("P1_captureScreenshot_png", lambda: cdp.call("Page.captureScreenshot", format="png")["data"])
        timed("P2_toDataURL_png",
              lambda: cdp.eval_json("document.getElementById('c').toDataURL('image/png')"))
        for quality in jpeg_qualities:
            key = f"P3_toDataURL_jpeg_q{quality:g}"
            expression = f"document.getElementById('c').toDataURL('image/jpeg', {quality})"
            timed(key, lambda expr=expression: cdp.eval_json(expr))
        for quality in jpeg_qualities:
            key = f"P4_captureScreenshot_jpeg_q{quality:g}"
            timed(key, lambda q=quality: cdp.call(
                "Page.captureScreenshot", format="jpeg", quality=int(q * 100))["data"])

    report = {}
    for key, values in samples.items():
        kept = c.drop_warmup(values, warmup)
        block = c.summarize(kept)
        block["bytes_median"] = c.summarize([float(x) for x in sizes.get(key, [0])])["median"] if sizes.get(key) else None
        report[key] = block
        report[key]["raw_ms"] = [round(v, 2) for v in kept]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="T1 取帧延迟与编码代价")
    parser.add_argument("--image", help="作为一帧画面的 PNG（用真实截图，别用纯色）")
    parser.add_argument("--frames", type=int, default=30, help="每条路径的有效采样数（默认 30）")
    parser.add_argument("--warmup", type=int, default=5, help="丢弃的前几帧（默认 5）")
    parser.add_argument("--batches", type=int, default=3, help="独立批次数，每批重新拉起浏览器（默认 3）")
    parser.add_argument("--sizes", default="1280x720", help="分辨率列表，如 1280x720,1920x1080")
    parser.add_argument("--jpeg-qualities", default="1.0,0.9,0.8", help="JPEG 质量列表")
    parser.add_argument("--headful", action="store_true", help="用可见窗口而不是 --headless=new")
    parser.add_argument("--allow-flat", action="store_true",
                        help="允许用低熵素材（仅验证脚本通路，数值不可外推）")
    parser.add_argument("--out", default="evidence", help="证据根目录")
    args = parser.parse_args()

    image = find_image(args.image)
    ratio = compression_ratio(image)
    if ratio is not None and ratio > 100 and not args.allow_flat:
        raise SystemExit(
            f"素材 {image.name} 的压缩比是 {ratio:.0f}:1，基本是纯色/低熵图。\n"
            "用这种图测出来的延迟会显著偏低，没有参考价值。\n"
            "请用一张真实游戏截图（--image），或明确加 --allow-flat 只验证脚本通路。"
        )
    if ratio is not None:
        print(f"素材压缩比 {ratio:.1f}:1"
              + ("（低熵，结果不可外推）" if ratio > 100 else "（有纹理，可外推）"))
    site, _ = prepare_site(image)
    qualities = [float(q) for q in args.jpeg_qualities.split(",")]
    sizes = []
    for item in args.sizes.split(","):
        width, _, height = item.partition("x")
        sizes.append((int(width), int(height)))

    evidence = c.Evidence("t1", pathlib.Path(args.out))
    print(f"素材：{image}  （base64 之前是 PNG，{image.stat().st_size} B）")
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")

    server, port = c.serve_directory(site)
    all_batches: list[dict] = []
    try:
        for batch in range(1, args.batches + 1):
            proc, devtools_port, data_dir = c.launch_chrome(
                f"http://127.0.0.1:{port}/index.html",
                headless=not args.headful,
                width=sizes[0][0], height=sizes[0][1],
            )
            try:
                cdp = c.Cdp(c.page_target(devtools_port, "index.html"))
                c.wait_for(cdp, "window.__ready === true", timeout=30)
                cdp.call("Emulation.setDeviceMetricsOverride", width=sizes[0][0], height=sizes[0][1],
                         deviceScaleFactor=1, screenWidth=sizes[0][0], screenHeight=sizes[0][1],
                         mobile=False)
                state = cdp.eval_json("window.__state()")
                print(f"\n批次 {batch} 页面状态：{state}")
                for width, height in sizes:
                    started = time.time()
                    block = measure_once(cdp, args.frames, args.warmup, width, height, qualities)
                    block["_size"] = f"{width}x{height}"
                    block["_elapsed_s"] = round(time.time() - started, 1)
                    all_batches.append(block)
                    print(f"  批次 {batch} 分辨率 {width}x{height} 用时 {block['_elapsed_s']}s")
                cdp.close()
            finally:
                proc.kill()
                shutil.rmtree(data_dir, ignore_errors=True)
    finally:
        server.shutdown()

    # 汇总：按 (路径, 分辨率) 汇总所有批次
    merged: dict[tuple[str, str], list[float]] = {}
    for block in all_batches:
        for key, value in block.items():
            if key.startswith("P") and isinstance(value, dict):
                merged.setdefault((key, block["_size"]), []).extend(value.get("raw_ms", []))

    print("\n结果（每行 = 一条路径 × 一个分辨率，跨批次合并）")
    rows = []
    for (key, size), values in sorted(merged.items()):
        stats = c.summarize(values)
        bytes_median = next(
            (b[key].get("bytes_median") for b in all_batches if key in b and b["_size"] == size), None
        )
        rows.append([
            key, size, f"{stats['median']:.1f}", f"{stats['p95']:.1f}",
            f"{stats['min']:.1f}", f"{stats['max']:.1f}", f"{stats['n']}",
            f"{bytes_median / 1024:.0f} KB" if bytes_median else "n/a",
        ])
    c.print_table(rows, ["路径", "分辨率", "median(ms)", "p95", "min", "max", "n", "每帧 base64"])

    evidence.write_json("summary.json", {f"{k[0]}@{k[1]}": c.summarize(v) for k, v in merged.items()})
    evidence.write_json("raw.json", all_batches)
    print("\n判读：")
    print("  1. 字节数是解释延迟的主因，先看它再看毫秒")
    print("  2. 若 JPEG@720p 落在 50-90 ms，则 #6696 的 190 ms 属 1080p JPEG 口径，方案可行性要重估")
    print("  3. 有损编码对识别的影响不归本脚本管，见 t2_jpeg_recognition.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
