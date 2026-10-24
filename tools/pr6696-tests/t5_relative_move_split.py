#!/usr/bin/env python3
"""T5 · relative_move 的分片与 >127 行为（验证 #6696 的 _MAX_RELATIVE_STEP = 127）

#6696 的 `cdp_controller.py` 里写着：

    _MAX_RELATIVE_STEP = 127   # 串流 SDK 单次只处理 127px 以内的 movementX/Y

这个 127 的依据来自 #6746 的 `CloudBridge.cpp:368-372` 注释，**没有实测来源**。
本脚本分三种模式，把「能测的」和「测不到的」分开：

  --mode browser   页面看到浏览器算出来的 movementX 是多少（验证浏览器是否透传大位移）
  --mode hook      页内注入（与 cdp_controller 的 INPUT_POLICY_JS 同构）后，页面看到的
                   值是否精确等于请求值（验证我们的注入没有丢精度）
  --mode game      在真实云游戏页面上只挂记录器、不注入钩子，观察页面（=SDK 的入参）
                   实际收到多少。**仍然不能直接证明 SDK 内部截断**——那要看画面转了多少，
                    需要配合 NCC 估计，属于 T4 的范畴。

结论怎么写：
  若 browser 模式显示 360→360，说明浏览器层不截断，127 这个上限只可能来自 SDK；
  若 hook 模式显示请求 360→收到 360，说明我们的分片逻辑本身不丢数据；
  若 game 模式显示 SDK 入参 360 而画面只转约 1/3，才是 SDK 截断的间接证据。

用法：
  python3 t5_relative_move_split.py --mode browser
  python3 t5_relative_move_split.py --mode hook
  python3 t5_relative_move_split.py --mode game --url https://endfield.hypergryph.com/cloud --port 9334
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile
import time

import _common as c

ANCHOR = (640, 360)
SWEEP = [60, 120, 127, 128, 200, 254, 300, 360]
REPEAT = 5


def prepare_site(with_image: bool) -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    site = pathlib.Path(tempfile.mkdtemp(prefix="t5-site-"))
    shutil.copy(here / "probe" / "index.html", site / "index.html")
    if with_image:
        candidate = here.parent / "linux-adapt" / "evidence-l1" / "f2-red.png"
        if candidate.exists():
            shutil.copy(candidate, site / "frame.png")
    return site


def read_last_movement(cdp: c.Cdp) -> tuple[int, int]:
    """读冒泡阶段的 mousemove。

    为什么必须是冒泡阶段：页内钩子在捕获阶段覆盖 movementX/Y，
    只有在它之后注册的监听器（冒泡阶段）读到的值，才等于下发给 SDK 的值。
    读捕获阶段只能证明浏览器原始输入，不能证明我们的注入生效。
    """
    expression = (
        "(() => { const hits = window.__log.filter(x => x.phase === 'bubble'"
        " && x.type === 'mousemove'); return hits.length ? hits[hits.length - 1] : null; })()"
    )
    payload = cdp.eval_json(expression)
    if not payload:
        return (0, 0)
    return (int(payload["mx"]), int(payload["my"]))


def sweep_browser(cdp: c.Cdp) -> list[dict]:
    """不用钩子：让浏览器根据指针位置差自己算 movementX。"""
    rows = []
    for delta in SWEEP:
        for _ in range(REPEAT):
            cdp.eval_json("window.__resetLog()")
            cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=ANCHOR[0], y=ANCHOR[1],
                     button="none", buttons=0)
            cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=ANCHOR[0] + delta, y=ANCHOR[1],
                     button="none", buttons=0)
            received = read_last_movement(cdp)
            rows.append({"requested": delta, "received": received[0], "mode": "browser"})
    return rows


def sweep_hook(cdp: c.Cdp) -> list[dict]:
    """装上与 cdp_controller 同构的钩子，验证注入值是否精确。"""
    # 必须先等页面脚本就绪：Runtime.evaluate 对不存在的函数只返回 exceptionDetails，
    # 不会抛错，容易造成「钩子没装上但脚本看起来跑完了」的假通过。
    c.wait_for(cdp, "typeof window.__installHook === 'function'", timeout=30)
    installed = cdp.eval_json("window.__installHook(640, 360)")
    if installed is not True:
        raise SystemExit(f"钩子安装失败：__installHook 返回 {installed!r}")
    rows = []
    for delta in SWEEP:
        for _ in range(REPEAT):
            cdp.eval_json("window.__resetLog()")
            cdp.call("Runtime.evaluate",
                     expression=f"window.__maaRelative = {{dx: {delta}, dy: 0}}",
                     returnByValue=True)
            cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=ANCHOR[0], y=ANCHOR[1],
                     button="none", buttons=0)
            received = read_last_movement(cdp)
            rows.append({"requested": delta, "received": received[0], "mode": "hook"})
    return rows


def sweep_game(cdp: c.Cdp) -> list[dict]:
    """真实页面：只挂记录器，不发注入钩子。观察页面（SDK 入参）收到多少。"""
    cdp.call("Runtime.evaluate", expression="""
        if (!window.__probeLog) {
            window.__probeLog = [];
            for (const t of ['mousemove', 'pointermove']) {
                window.addEventListener(t, (e) => {
                    window.__probeLog.push({mx: e.movementX | 0, my: e.movementY | 0,
                                            x: e.clientX, y: e.clientY, t: performance.now()});
                }, {capture: true, passive: true});
            }
        }
        1
    """, returnByValue=True)
    rows = []
    for delta in SWEEP:
        for _ in range(REPEAT):
            cdp.call("Runtime.evaluate", expression="window.__probeLog = []", returnByValue=True)
            cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=ANCHOR[0], y=ANCHOR[1],
                     button="none", buttons=0)
            cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=ANCHOR[0] + delta, y=ANCHOR[1],
                     button="none", buttons=0)
            time.sleep(0.02)
            log = cdp.eval_json("window.__probeLog") or []
            received = max((abs(int(entry["mx"])) for entry in log), default=0)
            rows.append({"requested": delta, "received": received, "mode": "game"})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="T5 relative_move 分片与 >127 行为")
    parser.add_argument("--mode", choices=["browser", "hook", "game"], default="browser")
    parser.add_argument("--url", help="game 模式必填：真实云游戏页面地址")
    parser.add_argument("--port", type=int, default=0, help="game 模式：附加到已运行的浏览器端口")
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    evidence = c.Evidence(f"t5-{args.mode}", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")

    proc = None
    data_dir = None
    server = None
    try:
        if args.mode == "game":
            if not args.url and not args.port:
                raise SystemExit("game 模式需要 --url（自己拉起浏览器）或 --port（附加到现有浏览器）")
            if args.port:
                devtools_port = args.port
            else:
                proc, devtools_port, data_dir = c.launch_chrome(args.url, headless=False)
            ws_url = c.page_target(devtools_port)
        else:
            site = prepare_site(with_image=args.mode != "hook")
            server, port = c.serve_directory(site)
            proc, devtools_port, data_dir = c.launch_chrome(
                f"http://127.0.0.1:{port}/index.html", headless=True)
            ws_url = c.page_target(devtools_port, "index.html")

        cdp = c.Cdp(ws_url)
        cdp.call("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1,
                 screenWidth=1280, screenHeight=720, mobile=False)

        if args.mode == "game":
            rows = sweep_game(cdp)
        elif args.mode == "hook":
            rows = sweep_hook(cdp)
            zeros = sum(1 for row in rows if row["received"] == 0)
            if zeros == len(rows):
                sample = cdp.eval_json("window.__log.slice(-5)") or []
                print("  [诊断] 冒泡阶段一条都没读到，最近 5 条日志：")
                for entry in sample:
                    print(f"    {entry}")
        else:
            c.wait_for(cdp, "window.__ready === true", timeout=30)
            rows = sweep_browser(cdp)

        grouped: dict[int, list[int]] = {}
        for row in rows:
            grouped.setdefault(row["requested"], []).append(row["received"])

        table = []
        verdict = []
        for requested in SWEEP:
            values = grouped.get(requested, [])
            if not values:
                continue
            unique = sorted(set(values))
            passed = all(value == requested for value in values)
            table.append([requested, "/".join(str(v) for v in unique), len(values),
                          "精确" if passed else "有偏差"])
            verdict.append((requested, passed, unique))

        print(f"\n模式：{args.mode}")
        c.print_table(table, ["请求 dx", "页面收到", "次数", "判定"])

        mismatched = [v for v in verdict if not v[1]]
        print("\n判读：")
        if args.mode == "browser":
            print("  - 全部精确 → 浏览器层不截断，127 只可能来自 SDK")
            print("  - 大位移被截断 → 需要重新审视 _MAX_RELATIVE_STEP 的依据")
        elif args.mode == "hook":
            print("  - 全部精确 → 页内注入没有丢精度，分片逻辑本身正确")
            print("  - 出现偏差 → 我们的 INPUT_POLICY_JS 或分片实现对不上，先修实现")
        else:
            print("  - 这里只能证明「SDK 的入参是多少」")
            print("  - SDK 内部是否截断，需要配合画面转角（t4）才能给出间接证据")
        if mismatched:
            print(f"  - 有 {len(mismatched)} 个请求值出现偏差：{mismatched}")

        evidence.write_json("summary.json", {"mode": args.mode, "rows": rows,
                                             "verdict": [{"requested": r, "exact": p, "samples": u}
                                                         for r, p, u in verdict]})
        cdp.close()
    finally:
        if proc is not None:
            proc.kill()
        if data_dir is not None:
            shutil.rmtree(data_dir, ignore_errors=True)
        if server is not None:
            server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
