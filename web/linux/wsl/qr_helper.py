#!/usr/bin/env python3
"""把页面推到「扫码登录」并把二维码裁出来。

流程：
  1. 读页面状态（landing / login / startup_error / stream …）
  2. landing        → 点「开始游戏」
     startup_error  → 点页面自己的「重新加载」（弱网第一遍 SDK 拉不完，第二遍走缓存）
     login          → 看登录面板是手机号还是二维码；不是二维码就点二维码图标切过去
  3. 截图 + 找出二维码元素矩形 + 裁切放大 3 倍

产物：<out>/qr-live.png（整页）、<out>/qr-only.png（二维码）

    python3 qr_helper.py --json /tmp/maaend-manual/launch.json --out /mnt/d/桌面/maaend-manual
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cdp_controller import _Sess

FIND_CLICKABLE = """(() => {
  const wanted = %s;
  const out = {};
  for (const label of wanted) {
    const el = [...document.querySelectorAll('a,button,span,div')]
      .find(e => e.children.length === 0 &&
                 (e.textContent || '').trim() === label &&
                 e.getClientRects().length);
    if (el) {
      const r = el.getBoundingClientRect();
      out[label] = [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)];
    }
  }
  return JSON.stringify(out);
})()"""

FIND_QR_TOGGLE = """(() => {
  const hits = [];
  document.querySelectorAll('img,canvas,svg,i,div,button').forEach(e => {
    const cls = typeof e.className === 'string' ? e.className : '';
    const text = (e.getAttribute('aria-label') || '') + (e.getAttribute('title') || '') +
                 (e.id || '') + cls + ((e.src || '').slice(-48));
    if (!/qr|二维码|扫码|scan/i.test(text)) return;
    const r = e.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return;
    hits.push([Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2),
               Math.round(r.width), Math.round(r.height), cls.slice(0, 30)]);
  });
  return JSON.stringify(hits.slice(0, 10));
})()"""

FIND_QR_IMAGE = """(() => {
  const out = [];
  document.querySelectorAll('img,canvas').forEach(e => {
    const r = e.getBoundingClientRect();
    if (r.width >= 120 && r.height >= 120) {
      out.push([Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]);
    }
  });
  out.sort((a, b) => Math.abs(a[2] - a[3]) - Math.abs(b[2] - b[3]));
  return JSON.stringify(out.slice(0, 6));
})()"""


def click(sess, x: float, y: float) -> None:
    sess.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y,
              button="left", buttons=1, clickCount=1, pointerType="mouse")
    time.sleep(0.05)
    sess.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y,
              button="left", buttons=0, clickCount=1, pointerType="mouse")


def body_text(sess) -> str:
    return (sess.ev("document.body.innerText.slice(0,400)") or "").replace("\n", " / ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()

    port = a.port or int(json.load(open(a.json, encoding="utf-8"))["cdp"].rsplit(":", 1)[-1])
    targets = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:%d/json/list" % port, timeout=5).read())
    pages = [t for t in targets
             if t.get("type") == "page" and "endfield" in (t.get("url") or "")]
    if not pages:
        print("没有 endfield 页面（浏览器在跑吗？）")
        return 1
    sess = _Sess(pages[0]["webSocketDebuggerUrl"])

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # 1) 遇到「页面启动未完成」先软重载一次
    text = body_text(sess)
    if "页面启动未完成" in text:
        print("页面停在「启动未完成」，重载一次（走缓存）…")
        hits = json.loads(sess.ev(FIND_CLICKABLE % json.dumps(["重新加载", "重新载入"])))
        if hits:
            click(sess, *hits[next(iter(hits))])
        else:
            sess.call("Page.reload")
        time.sleep(8)
        text = body_text(sess)

    # 2) 落地页 → 开始游戏
    if "开始游戏" in text and "请输入手机号" not in text:
        hits = json.loads(sess.ev(FIND_CLICKABLE % json.dumps(["开始游戏"])))
        if hits:
            print("点「开始游戏」")
            click(sess, *hits["开始游戏"])
            time.sleep(6)
            text = body_text(sess)

    # 3) 登录面板：切成扫码
    if "请输入手机号" in text or "发送验证码" in text:
        toggles = json.loads(sess.ev(FIND_QR_TOGGLE))
        print("登录面板候选元素:", toggles)
        # 优先取尺寸 40~90 的方形小图标（就是二维码切换按钮）
        pick = next((t for t in toggles if 30 <= t[2] <= 100 and 30 <= t[3] <= 100), None)
        if pick is None:
            pick = toggles[0] if toggles else None
        if pick:
            print("点二维码图标", pick[:2])
            click(sess, pick[0], pick[1])
            time.sleep(3)

    # 4) 截图（kiosk/wayland 下必须 fromSurface=True，否则 data 是空的）
    shot = sess.call("Page.captureScreenshot", format="png", fromSurface=True)
    data = shot.get("data", "")
    if not data:
        print("截图返回空")
        return 1
    live = out / "qr-live.png"
    live.write_bytes(base64.b64decode(data))
    print("整页截图:", live)

    # 5) 找二维码矩形并裁切放大
    cands = json.loads(sess.ev(FIND_QR_IMAGE))
    if not cands:
        print("页面上没找到 >=120px 的图片元素，可能还在加载；整页图见", live)
        return 0
    x, y, w, h = cands[0]
    pad = 20
    try:
        from PIL import Image

        im = Image.open(live)
        box = (max(0, x - pad), max(0, y - pad),
               min(im.width, x + w + pad), min(im.height, y + h + pad))
        crop = im.crop(box)
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
        qr = out / "qr-only.png"
        crop.save(qr)
        print("二维码:", qr, crop.size)
    except Exception as e:
        print("裁切失败（装 Pillow 可自动裁）：", e)

    print("页面文字:", text[:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
