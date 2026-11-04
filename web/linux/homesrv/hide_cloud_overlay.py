#!/usr/bin/env python3
"""隐藏云·终末地网页端的浮层：悬浮球 + 网络延迟指示（信号条 + "5ms"）。

沿用 hide_cloud_ball.py 的机制（CDP 注入 CSS + MutationObserver + 新标签页脚本），
只是把目标从「悬浮球」扩到「延迟指示器」。延迟指示器的 class 名未知时**不需要预先知道**：
先按文本 `/^\\d+\\s*ms$/` 找，命中后把它的父容器一起隐藏；再用「右下角 + fixed/absolute +
小尺寸」几何规则兜底。

用法（在 homesrv 上，chrome 已带 --remote-debugging-port=9334）：
    python3 hide_cloud_overlay.py --check    # 只探测：列出候选元素（class/位置/文本），不改动
    python3 hide_cloud_overlay.py            # 注入一次（所有 endfield 页面）
    python3 hide_cloud_overlay.py --watch    # 常驻，每 2s 检查（日常跑期间用）
    python3 hide_cloud_overlay.py --ball-only  # 只关悬浮球（退化成 hide_cloud_ball.py 的行为）

注意：`--check` 的输出请贴回来，据此可以把选择器固化成静态 CSS（比几何规则稳）。
"""

import contextlib
import json
import os
import sys
import time
import urllib.request

import websocket  # type: ignore

DST = "http://127.0.0.1:9334"

# ── 悬浮球（已知 class，沿用 hide_cloud_ball.py）───────────────────────────────
BALL_CSS = '[class*="hbU_7F"],[class*="e4MbkW"]{display:none!important;visibility:hidden!important}'
# ── 网络延迟指示器（2026-10-29 在 homesrv 云网页端实测的 class）─────────────────
# 容器 div._gEApb.b9Vf6r  [1208,666,40,38]，内含 span.K_iy0u "9ms" [1216,689,23,13]
# 该容器与「进入协议空间」按钮的 26x26 圆图标命中框 [1210,649,26,26] 在 y 666~675 重叠，
# 是 WhiteConfirmButtonType1 掉到 0.848 的原因之一。CSS Modules 哈希会随版本变，故保留
# 文本/几何兜底规则。
PING_CSS = '[class*="_gEApb"],[class*="K_iy0u"]{display:none!important;visibility:hidden!important}'

# ── 页面策略（移植自 CloudShell scripts/cloud_policy.js）──────────────────────
# movement 归零 / keydown 补 mouseenter / document.hidden / 拒绝指针锁定 / 禁用 WebGL2
# 文件与脚本同目录；缺失时只告警，不影响浮层隐藏。
POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_policy_linux.js")


def load_policy():
    try:
        with open(POLICY_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        print("[policy] 读取失败，跳过: %s" % e)
        return ""


POLICY_JS = load_policy()

INIT_JS = r"""
(() => {
  const BALL_CSS = '""" + BALL_CSS + r"""';
  const PING_CSS = '""" + PING_CSS + r"""';
  const MARK = 'data-hermes-hidden';

  function ensureStyle() {
    if (document.getElementById('hermes-hide-overlay')) return;
    const s = document.createElement('style');
    s.id = 'hermes-hide-overlay';
    s.textContent = BALL_CSS + PING_CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  // 悬浮球：class 优先，几何兜底（左上角 20~90px 的浮层）
  function hideBall() {
    let n = 0;
    for (const sel of ['[class*="hbU_7F"]', '[class*="e4MbkW"]']) {
      for (const e of document.querySelectorAll(sel)) {
        e.style.setProperty('display', 'none', 'important');
        n++;
      }
    }
    if (n) return n;
    for (const e of document.querySelectorAll('div')) {
      const st = getComputedStyle(e);
      if (st.position !== 'fixed' && st.position !== 'absolute') continue;
      const r = e.getBoundingClientRect();
      if (r.width >= 20 && r.width <= 90 && r.height >= 20 && r.height <= 90 &&
          r.left >= -60 && r.left <= 120 && r.top >= -5 && r.top <= 150) {
        e.style.setProperty('display', 'none', 'important');
        n++;
      }
    }
    return n;
  }

  // 延迟指示器：文本 /\d+ms/i 的元素 → 连同最多两层父容器一起隐藏
  function hidePingByText() {
    const re = /^\s*\d{1,4}\s*(ms|fps)\s*$/i;
    let n = 0;
    for (const e of document.querySelectorAll('div,span,p,label')) {
      const t = (e.textContent || '').trim();
      if (!re.test(t)) continue;
      if (e.children.length > 2) continue;          // 避免把整块容器当目标
      const r = e.getBoundingClientRect();
      if (r.width > 400 || r.height > 200) continue; // 太大不像计数条
      let target = e;
      for (let i = 0; i < 2 && target.parentElement; i++) {
        const pr = target.parentElement.getBoundingClientRect();
        if (pr.width <= 420 && pr.height <= 220) target = target.parentElement;
        else break;
      }
      target.style.setProperty('display', 'none', 'important');
      target.setAttribute(MARK, 'ping');
      n++;
    }
    return n;
  }

  // 几何兜底：右下角 260x140 区域里的小浮层（信号条容器通常就这么大）
  function hidePingByGeometry() {
    const W = window.innerWidth, H = window.innerHeight;
    let n = 0;
    for (const e of document.querySelectorAll('div')) {
      const st = getComputedStyle(e);
      if (st.position !== 'fixed' && st.position !== 'absolute') continue;
      const r = e.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.width > 300 || r.height > 140) continue;
      if (r.left < W - 300 || r.top < H - 160) continue;
      if ((e.textContent || '').trim().length > 12) continue;
      e.style.setProperty('display', 'none', 'important');
      e.setAttribute(MARK, 'geo');
      n++;
    }
    return n;
  }

  function apply() {
    ensureStyle();
    const ball = hideBall();
    let ping = hidePingByText();
    if (!ping) ping = hidePingByGeometry();
    window.__hermesOverlayHidden = {ball, ping, t: Date.now()};
    return ball + ping;
  }

  window.__hermesApplyOverlay = apply;
  apply();
  document.addEventListener('DOMContentLoaded', apply);
  try {
    new MutationObserver(apply).observe(document.documentElement,
      {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style']});
  } catch (e) {}
  setInterval(apply, 1000);
})();
"""

CHECK_JS = r"""
(() => {
  const out = {url: location.href, size: [innerWidth, innerHeight], ball: [], ping: [], geo: []};
  for (const sel of ['[class*="hbU_7F"]', '[class*="e4MbkW"]']) {
    for (const e of document.querySelectorAll(sel)) {
      const r = e.getBoundingClientRect();
      out.ball.push({cls: String(e.className).slice(0, 60), x: Math.round(r.x), y: Math.round(r.y),
                     w: Math.round(r.width), h: Math.round(r.height),
                     shown: getComputedStyle(e).display !== 'none'});
    }
  }
  const re = /^\s*\d{1,4}\s*(ms|fps)\s*$/i;
  for (const e of document.querySelectorAll('div,span,p,label')) {
    const t = (e.textContent || '').trim();
    if (!re.test(t)) continue;
    if (e.children.length > 2) continue;
    const r = e.getBoundingClientRect();
    if (r.width > 400 || r.height > 200) continue;
    out.ping.push({text: t, cls: String(e.className).slice(0, 60), tag: e.tagName,
                   parentCls: String(e.parentElement && e.parentElement.className).slice(0, 60),
                   x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
                   shown: getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden'});
  }
  const W = innerWidth, H = innerHeight;
  for (const e of document.querySelectorAll('div')) {
    const st = getComputedStyle(e);
    if (st.position !== 'fixed' && st.position !== 'absolute') continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.width > 300 || r.height > 140) continue;
    if (r.left < W - 300 || r.top < H - 160) continue;
    out.geo.push({cls: String(e.className).slice(0, 60), x: Math.round(r.x), y: Math.round(r.y),
                  w: Math.round(r.width), h: Math.round(r.height),
                  text: (e.textContent || '').trim().slice(0, 20)});
  }
  return JSON.stringify(out);
})()
"""


def targets():
    try:
        with urllib.request.urlopen(DST + "/json", timeout=5) as r:
            return json.load(r)
    except Exception:
        return []


def endfield_pages():
    return [t for t in targets() if t.get("type") == "page" and "endfield" in (t.get("url") or "")]


class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=20, suppress_origin=True)
        self.i = 0

    def call(self, method, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                return msg

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("result", {}).get("value")

    def close(self):
        with contextlib.suppress(Exception):
            self.ws.close()


def main():
    watch = "--watch" in sys.argv
    check = "--check" in sys.argv

    if check and not watch:
        for t in endfield_pages():
            try:
                c = CDP(t["webSocketDebuggerUrl"])
                print("%s\n  %s" % (t.get("url", "")[:70], c.js(CHECK_JS)))
                c.close()
            except Exception as e:
                print("ERR", e)
        return 0

    registered = set()
    while True:
        for t in endfield_pages():
            tid = t.get("id")
            try:
                c = CDP(t["webSocketDebuggerUrl"])
                if tid not in registered:
                    if POLICY_JS:
                        c.call("Page.addScriptToEvaluateOnNewDocument", source=POLICY_JS)
                    c.call("Page.addScriptToEvaluateOnNewDocument", source=INIT_JS)
                    registered.add(tid)
                if POLICY_JS:
                    c.js(POLICY_JS)
                c.js(INIT_JS)
                pol = c.js("JSON.stringify(window.__hermesCloudPolicy||{})")
                ov = c.js("JSON.stringify(window.__hermesOverlayHidden||{})")
                print("%s policy=%s overlay=%s" % (tid, pol, ov))
                c.close()
            except Exception as e:
                print("注入失败", tid, str(e)[:60])
        if not watch:
            return 0
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
