#!/usr/bin/env python3
"""T1b · CDP 取帧延迟：七条通路逐条实测（回答「这个方案能不能成立」）

背景：#6696 实测「1080p JPEG 约 190ms 一帧」，而导航类任务对这个延迟敏感。
没有共享内存时，帧只能以 base64 从页面回传，所以要问清楚：

    1. 190ms 花在哪：页面内编码 / base64 传输 / Python 解码？
    2. 换成原始 RGBA（免解码）会不会更快？
    3. 720p 降到多少，能不能撑住导航？

七条通路：

    cdp_png        Page.captureScreenshot      PNG
    cdp_jpeg90     Page.captureScreenshot      JPEG q90
    cdp_jpeg75     Page.captureScreenshot      JPEG q75
    video_png      video → canvas → toDataURL  PNG（取视频原生帧）
    video_jpeg90   video → canvas → toDataURL  JPEG q90
    video_jpeg75   video → canvas → toDataURL  JPEG q75
    video_raw      video → canvas → getImageData → RGBA → base64（零解码）

每条记录三段耗时：js_ms（页面内）、total_ms（端到端，含传输）、decode_ms（Python 侧）。

判据：
    - 压缩比守卫：PNG 的 raw/payload > 100 说明画面接近纯色，延迟数字不可用（T1 的教训）
    - 换帧守卫：间隔 300ms 取两帧，字节必须不同，否则说明读到缓存帧

用法：
    python3 t1b_frame_paths.py --port 9334 --repeat 12
    python3 t1b_frame_paths.py --port 9334 --viewport 1920x1080
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import statistics
import sys
import time

import cv2
import numpy as np

import _common as c

PATHS = ("cdp_png", "cdp_jpeg90", "cdp_jpeg75",
         "video_png", "video_jpeg90", "video_jpeg75", "video_raw")

# 页面内取帧脚本：返回 {b64, js_ms, w, h}；b64 不带 data URL 前缀
JS_CAPTURE = r"""
(() => {
  const mode = %MODE%;
  const video = document.querySelector('video');
  const t0 = performance.now();
  let b64 = '', w = 0, h = 0;

  if (mode === 'video') {
    if (!video) return {err: 'no-video'};
    w = video.videoWidth; h = video.videoHeight;
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    cv.getContext('2d').drawImage(video, 0, 0, w, h);
    const url = cv.toDataURL('image/' + %FMT%, %QUALITY%);
    b64 = url.slice(url.indexOf(',') + 1);
  } else if (mode === 'video_raw') {
    if (!video) return {err: 'no-video'};
    w = video.videoWidth; h = video.videoHeight;
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    const ctx = cv.getContext('2d', {willReadFrequently: true});
    ctx.drawImage(video, 0, 0, w, h);
    const img = ctx.getImageData(0, 0, w, h);
    const bytes = new Uint8Array(img.data.buffer);
    b64 = typeof bytes.toBase64 === 'function' ? bytes.toBase64() : (() => {
      let s = '';
      for (let i = 0; i < bytes.length; i += 0x8000) {
        s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      return btoa(s);
    })();
  }
  return {b64: b64, js_ms: performance.now() - t0, w: w, h: h};
})()
"""


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle

    def ping(self) -> float:
        start = time.perf_counter()
        self.cdp.call("Runtime.evaluate", expression="1", returnByValue=True)
        return (time.perf_counter() - start) * 1000

    def js_capture(self, mode: str, fmt: str = "jpeg", quality: float = 0.9) -> dict:
        expr = (JS_CAPTURE.replace("%MODE%", json.dumps(mode))
                .replace("%FMT%", json.dumps(fmt))
                .replace("%QUALITY%", str(quality)))
        payload = self.cdp.call("Runtime.evaluate", expression=expr, returnByValue=True)
        return payload["result"]["value"]

    def cdp_shot(self, fmt: str, quality: int = 90) -> dict:
        params = {"format": fmt}
        if fmt == "jpeg":
            params["quality"] = quality
        started = time.perf_counter()
        data = self.cdp.call("Page.captureScreenshot", **params)["data"]
        return {"b64": data, "js_ms": float("nan"), "w": 0, "h": 0,
                "transport_ms": (time.perf_counter() - started) * 1000}


def run_one(probe: Probe, name: str) -> dict:
    """跑一次，返回端到端/页面内/解码三段耗时与体积。"""
    started = time.perf_counter()
    if name.startswith("cdp_"):
        fmt = "png" if name.endswith("png") else "jpeg"
        quality = 90 if name.endswith("90") else 75
        got = probe.cdp_shot(fmt, quality)
        decode_kind = fmt
    elif name == "video_raw":
        got = probe.js_capture("video_raw")
        decode_kind = "raw"
    else:
        fmt = "png" if name.endswith("png") else "jpeg"
        quality = 90 if name.endswith("90") else 75
        got = probe.js_capture("video", fmt, quality)
        decode_kind = fmt
    total_ms = (time.perf_counter() - started) * 1000

    if got.get("err"):
        return {"name": name, "error": got["err"]}

    b64 = got["b64"]
    raw = base64.b64decode(b64)
    decode_started = time.perf_counter()
    if decode_kind == "raw":
        w, h = got["w"], got["h"]
        rgba = np.frombuffer(raw, np.uint8).reshape(h, w, 4)
        frame = rgba[:, :, :3][:, :, ::-1].copy()   # RGBA → BGR
    else:
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    decode_ms = (time.perf_counter() - decode_started) * 1000

    return {
        "name": name,
        "total_ms": total_ms,
        "js_ms": got.get("js_ms"),
        "decode_ms": decode_ms,
        "b64_bytes": len(b64),
        "raw_bytes": len(raw),
        "frame_bytes": int(frame.nbytes) if frame is not None else 0,
        "shape": tuple(int(v) for v in frame.shape) if frame is not None else None,
        "mean_bgr": [round(float(v), 1) for v in frame.reshape(-1, 3).mean(axis=0)] if frame is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="T1b CDP 取帧延迟七条通路")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--repeat", type=int, default=12)
    parser.add_argument("--paths", default=",".join(PATHS))
    parser.add_argument("--view", default="", help="如 1920x1080；缺省用当前视口")
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    names = [v.strip() for v in args.paths.split(",") if v.strip()]
    evidence = c.Evidence("t1b", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    probe = Probe(args.port, 0.3)

    viewport = probe.cdp.eval_json("[innerWidth, innerHeight, devicePixelRatio]")
    video = probe.cdp.eval_json("""(() => {
      const v = document.querySelector('video');
      return v ? [v.videoWidth, v.videoHeight, v.paused, v.readyState] : null;
    })()""")
    print(f"视口 {viewport}  视频 {video}")
    if video is None:
        print("\n页面上没有 <video>：当前不在游戏内。请先进大世界再跑。")
        return 2

    override = None
    if args.view:
        width, height = (int(v) for v in args.view.lower().split("x"))
        probe.cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                       deviceScaleFactor=1, mobile=False)
        override = (width, height)
        time.sleep(0.5)
        print(f"已切换到视口 {width}x{height}")

    print(f"\n空跑 CDP 往返：{statistics.median([probe.ping() for _ in range(5)]):.2f} ms")

    # 换帧守卫：间隔 300ms 两帧必须不同
    first = probe.js_capture("video", "jpeg", 0.9)["b64"][:20000]
    time.sleep(0.3)
    second = probe.js_capture("video", "jpeg", 0.9)["b64"][:20000]
    changing = first != second
    print(f"换帧守卫：{'通过（帧在变）' if changing else '失败（读到静止/缓存帧）'}")

    results: dict[str, list[dict]] = {}
    for name in names:
        samples = []
        for _ in range(args.repeat):
            got = run_one(probe, name)
            if "error" in got:
                print(f"  {name}: {got['error']}")
                break
            samples.append(got)
            time.sleep(0.05)
        if samples:
            results[name] = samples

    print("\n路径            帧尺寸      payload   js(中位)  total(中位)  p95     decode(中位)  压缩比")
    summary = {}
    for name, samples in results.items():
        total = [s["total_ms"] for s in samples]
        js = [s["js_ms"] for s in samples if s["js_ms"] == s["js_ms"]]
        decode = [s["decode_ms"] for s in samples]
        payload = statistics.median([s["b64_bytes"] for s in samples])
        frame_bytes = statistics.median([s["frame_bytes"] for s in samples])
        shape = samples[0]["shape"]
        ratio = frame_bytes / payload if payload else 0
        summary[name] = {
            "n": len(samples),
            "shape": list(shape) if shape else None,
            "payload_bytes": int(payload),
            "js_ms": round(statistics.median(js), 1) if js else None,
            "total_ms": round(statistics.median(total), 1),
            "total_p95_ms": round(sorted(total)[max(0, int(len(total) * 0.95) - 1)], 1),
            "decode_ms": round(statistics.median(decode), 1),
            "frame_bytes": int(frame_bytes),
            "compression_ratio": round(ratio, 1),
            "mean_bgr": samples[0]["mean_bgr"],
        }
        s = summary[name]
        print(f"{name:14s} {str(shape):12s} {payload/1024:7.0f}K {str(s['js_ms']):>9s} "
              f"{s['total_ms']:10.1f}  {s['total_p95_ms']:6.1f}  {s['decode_ms']:11.1f}  {ratio:6.1f}")

    if override:
        probe.cdp.call("Emulation.clearDeviceMetricsOverride")

    print("\n判读")
    best = min((s for s in summary.values() if s["compression_ratio"] > 20),
               key=lambda s: s["total_ms"], default=None)
    if best:
        fps = 1000.0 / best["total_ms"]
        print(f"  最快可用通路：{best['total_ms']:.1f} ms/帧 → 上限 {fps:.1f} fps")
    print("  total = 页面内(js) + base64 传输 + Python 解码，三者相加应与 total 接近")
    print("  compression_ratio 太低（<20）说明画面接近纯色，该行数字不可用")
    print("  导航参考：190ms≈5.3fps、100ms≈10fps、60ms≈16.7fps（识别耗时不在此列）")

    evidence.write_json("summary.json", {
        "viewport": viewport, "video": video, "changing": changing,
        "override": override, "paths": summary,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
