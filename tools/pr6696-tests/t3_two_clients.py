#!/usr/bin/env python3
"""T3 · 两个 CDP 客户端并发（验证 #6696 的风险 3 断言）

#6807 把「两个 CDP 客户端同时连一个页面」列为风险，作者判断「可能性比较小」。
#6696 的实现里确实是这样用的：控制器持有 `--remote-debugging-pipe`，而外部探针
（我们的抓帧脚本、页面状态检查）用端口客户端。本脚本回答三个问题：

1. 两个客户端**同时连接**是否互相踢掉（能不能共存）
2. 一个客户端高频截图时，另一个客户端的输入是否变慢或丢事件
3. 两个客户端**同时发输入**时，页面收到几次（串扰）

注意：本脚本用两个端口客户端（WebSocket）模拟并发，因为 pipe 必须在拉起浏览器时
占用 fd，无法在已启动的浏览器上后加。测试结论对「两个会话抢同一页面」这个机制成立，
但**没有覆盖 pipe 与 port 混合**的路径——那一项要另测（见 README「未覆盖」）。

用法：
  python3 t3_two_clients.py --frames 30
  python3 t3_two_clients.py --frames 30 --screencap-hz 10
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import statistics
import sys
import tempfile
import threading
import time

import _common as c

ANCHOR = (640, 360)


def dispatch_move(cdp: c.Cdp, x: int, y: int) -> float:
    start = time.perf_counter()
    cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="none", buttons=0)
    return (time.perf_counter() - start) * 1000.0


def prepare_site() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    site = pathlib.Path(tempfile.mkdtemp(prefix="t3-site-"))
    shutil.copy(here / "probe" / "index.html", site / "index.html")
    return site


def run_input_sequence(cdp: c.Cdp, frames: int) -> list[float]:
    durations = []
    for i in range(frames):
        x = ANCHOR[0] + (i % 7) * 3
        durations.append(dispatch_move(cdp, x, ANCHOR[1]))
        time.sleep(0.02)
    return durations


def main() -> int:
    parser = argparse.ArgumentParser(description="T3 两个 CDP 客户端并发")
    parser.add_argument("--frames", type=int, default=30, help="每轮输入次数（默认 30）")
    parser.add_argument("--screencap-hz", type=float, default=10.0, help="并发截图频率（默认 10）")
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    site = prepare_site()
    server, port = c.serve_directory(site)
    evidence = c.Evidence("t3", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")

    proc, devtools_port, data_dir = c.launch_chrome(
        f"http://127.0.0.1:{port}/index.html", headless=True)
    result: dict = {}
    try:
        ws_url = c.page_target(devtools_port, "index.html")
        client_a = c.Cdp(ws_url)
        client_b = c.Cdp(ws_url)
        for session in (client_a, client_b):
            session.call("Emulation.setDeviceMetricsOverride", width=1280, height=720,
                         deviceScaleFactor=1, screenWidth=1280, screenHeight=720, mobile=False)
        c.wait_for(client_a, "window.__ready === true", timeout=30)

        # --- 1. 共存性 ---
        proxy_a = client_a.eval_json("1 + 1")
        proxy_b = client_b.eval_json("2 + 2")
        result["coexist"] = {"client_a": proxy_a, "client_b": proxy_b,
                             "both_alive": proxy_a == 2 and proxy_b == 4}
        print(f"\n[1] 共存：A={proxy_a} B={proxy_b} → {'可以共存' if result['coexist']['both_alive'] else '互相踢掉'}")

        # --- 2. 基线：只有 A 发输入 ---
        mute = "(window.__log.filter(x => x.type === 'pointermove' && x.phase === 'capture')).length"
        client_a.eval_json("window.__resetLog()")
        baseline = run_input_sequence(client_a, args.frames)
        baseline_log = client_a.eval_json(mute)

        # --- 3. 并发：B 高频截图，同时 A 发同样序列 ---
        stop = threading.Event()
        screencap_durations: list[float] = []

        def screencap_loop() -> None:
            interval = 1.0 / max(args.screencap_hz, 0.1)
            while not stop.is_set():
                start = time.perf_counter()
                try:
                    client_b.call("Page.captureScreenshot", format="jpeg", quality=80)
                except Exception as exc:  # noqa: BLE001 - 记录失败原因而不是崩掉
                    screencap_durations.append(-1.0)
                    result.setdefault("screencap_errors", []).append(str(exc))
                screencap_durations.append((time.perf_counter() - start) * 1000.0)
                time.sleep(interval)

        client_a.eval_json("window.__resetLog()")
        worker = threading.Thread(target=screencap_loop, daemon=True)
        worker.start()
        time.sleep(0.2)
        concurrent = run_input_sequence(client_a, args.frames)
        stop.set()
        worker.join(timeout=5)
        concurrent_log = client_a.eval_json(mute)

        result["input_latency"] = {
            "baseline": c.summarize(baseline),
            "concurrent": c.summarize(concurrent),
            "baseline_events": baseline_log,
            "concurrent_events": concurrent_log,
            "expected_events": args.frames,
        }
        result["screencap_while_inputting"] = c.summarize([v for v in screencap_durations if v >= 0])

        print(f"[2] 输入延迟（ms）：基线 median={statistics.median(baseline):.1f} "
              f"并发 median={statistics.median(concurrent):.1f}")
        print(f"    页面收到事件：基线 {baseline_log} / 并发 {concurrent_log} / 期望 {args.frames}")
        print(f"    并发截图：{result['screencap_while_inputting'].get('n', 0)} 次，"
              f"median={result['screencap_while_inputting'].get('median', 0):.0f} ms")

        # --- 4. 双向输入：两个客户端几乎同时点不同位置 ---
        client_a.eval_json("window.__resetLog()")

        def click(session: c.Cdp, x: int, y: int) -> None:
            session.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y,
                         button="left", buttons=1, clickCount=1)
            session.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y,
                         button="left", buttons=0, clickCount=1)

        threads = [threading.Thread(target=click, args=(client_a, 400, 300)),
                   threading.Thread(target=click, args=(client_b, 900, 500))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        clicks = client_a.eval_json("window.__clicks")
        result["bidirectional_clicks"] = {"received": clicks, "expected_if_no_crosstalk": 2}
        print(f"[3] 双向同时点击：页面收到 {clicks} 次（无串扰应为 2）")

        client_a.close()
        client_b.close()
    finally:
        proc.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
        server.shutdown()

    evidence.write_json("summary.json", result)
    print("\n判读：")
    print("  - 若 concurrent median 明显高于 baseline，或收到事件数 < 期望，说明截图会挤占输入")
    print("  - 若双向点击收到 2 次，说明两个会话的输入不会互相吞掉（不等于不会重复触发）")
    print("  - 本脚本未覆盖 pipe+port 混合路径，见 README「未覆盖」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
