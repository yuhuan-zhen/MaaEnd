#!/usr/bin/env python3
"""T6 · Chrome 启动参数单条消融（验证 #6696 的 Chrome 启动参数清单）

#6696 用的是「kiosk 模式 Chrome + 调试端口 + DSF 1.5」，#6807 的 4.1 节则要求
`--app`、`--remote-debugging-port=0`、独立 `--user-data-dir`、防节流参数。
本脚本逐条去掉某个参数，测可观察症状——不是「这条很重要」，而是「删了会怎样」。

四组可测项：
  1. `--remote-debugging-port=0`  → DevToolsActivePort 文件是否生成（拿不到端口就没法连）
  2. `--user-data-dir=<独立>`     → profile 目录是否独立创建（否则登录态互相污染）
  3. `--force-device-scale-factor=1` → devicePixelRatio 是否被系统 DSF 影响
  4. 防节流参数组                  → 页面切到后台后 rAF 帧率是否塌陷

`--app` 的可观察症状是「有没有地址栏/标签栏」，headless 下不可测，需要 DISPLAY；
没有 DISPLAY 时该项记 n/a，不伪造结论。

用法：
  python3 t6_chrome_flags.py
  python3 t6_chrome_flags.py --with-app   # 有 DISPLAY 时连 --app 一起测
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

import _common as c

ANTI_THROTTLE = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


def prepare_site() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    site = pathlib.Path(tempfile.mkdtemp(prefix="t6-site-"))
    shutil.copy(here / "probe" / "index.html", site / "index.html")
    return site


def launch_custom(url: str, flags: list[str], *, headless: bool = True, data_dir: pathlib.Path | None = None):
    """比 _common.launch_chrome 更底层的拉起，用来精确控制 flag 集合。"""
    binary = c.chrome_binary()
    own_dir = data_dir is None
    if data_dir is None:
        data_dir = pathlib.Path(tempfile.mkdtemp(prefix="t6-profile-"))
    argv = [binary, f"--user-data-dir={data_dir}", "--no-first-run", "--no-default-browser-check",
            "--window-size=1280,720", *flags]
    if headless:
        argv.append("--headless=new")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        argv += ["--no-sandbox", "--disable-dev-shm-usage"]
    argv.append(url)
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port_file = data_dir / "DevToolsActivePort"
    port = 0
    for _ in range(200):
        if port_file.exists() and port_file.stat().st_size > 0:
            port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    return proc, port, data_dir, own_dir


def raf_fps_when_hidden(cdp: c.Cdp, sample_ms: int = 1500) -> float:
    """把页面切到后台（激活另一个 target），再测 rAF 帧率。

    原理：`Target.activateTarget` 会让原页面收到真实的 visibilitychange，
    这比伪造 document.visibilityState 更接近「用户切走窗口」的真实情况。
    """
    own_id = ""
    for info in cdp.call("Target.getTargets").get("targetInfos", []):
        if info.get("type") == "page" and "index.html" in info.get("url", ""):
            own_id = info.get("targetId", "")
            break
    created = cdp.call("Target.createTarget", url="about:blank")
    other_id = created.get("targetId")
    cdp.call("Target.activateTarget", targetId=other_id)
    time.sleep(0.3)
    fps = cdp.eval_json(f"window.__rafFps({sample_ms})")
    try:
        cdp.call("Target.closeTarget", targetId=other_id)
        if own_id:
            cdp.call("Target.activateTarget", targetId=own_id)
    except Exception:  # noqa: BLE001 - 恢复失败不影响结论
        pass
    return float(fps or 0.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="T6 Chrome 启动参数消融")
    parser.add_argument("--with-app", action="store_true", help="额外测 --app（需要 DISPLAY）")
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    site = prepare_site()
    server, site_port = c.serve_directory(site)
    url = f"http://127.0.0.1:{site_port}/index.html"
    evidence = c.Evidence("t6", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")

    rows: list[list[str]] = []
    detail: dict = {}

    def probe(label: str, flags: list[str], measure):
        proc, port, data_dir, own = launch_custom(url, flags)
        try:
            if not port:
                rows.append([label, "启动失败（拿不到调试端口）", "-", "这正是预期症状"])
                detail[label] = {"error": "no debug port"}
                return None
            cdp = c.Cdp(c.page_target(port, "index.html"))
            c.wait_for(cdp, "window.__ready === true", timeout=30)
            value, note = measure(cdp, port, data_dir)
            rows.append([label, note, str(value), ""])
            detail[label] = {"value": value, "note": note}
            cdp.close()
            return value
        finally:
            proc.kill()
            if own:
                shutil.rmtree(data_dir, ignore_errors=True)

    try:
        # 1. 调试端口：有 vs 无
        probe("基线（含 --remote-debugging-port=0）", ["--remote-debugging-port=0",
                                                       "--force-device-scale-factor=1"] + ANTI_THROTTLE,
              lambda cdp, port, _: (port, "DevToolsActivePort 生成，端口可读"))
        probe("去掉 --remote-debugging-port=0", ["--force-device-scale-factor=1"] + ANTI_THROTTLE,
              lambda cdp, port, _: (port, "没有端口文件 → 客户端无法连接"))

        # 2. DSF：有 vs 无
        dsf_forced = probe("基线 DSF=1", ["--remote-debugging-port=0", "--force-device-scale-factor=1"],
                           lambda cdp, port, _: (cdp.eval_json("window.devicePixelRatio"), "devicePixelRatio"))
        dsf_natural = probe("去掉 --force-device-scale-factor=1", ["--remote-debugging-port=0"],
                            lambda cdp, port, _: (cdp.eval_json("window.devicePixelRatio"),
                                                  "跟随系统 DSF"))
        if dsf_forced is not None and dsf_forced == dsf_natural:
            rows.append(["DSF 对照结论", "本机不可区分", str(dsf_forced),
                         "系统 DSF 本来就是 1，需要 125%/150% 的机器才能验证"])

        # 3. 防节流：有 vs 无（页面切到后台后测 rAF）
        throttle_on = probe("基线（含防节流组，后台 rAF）", ["--remote-debugging-port=0"] + ANTI_THROTTLE,
                            lambda cdp, port, _: (round(raf_fps_when_hidden(cdp), 1), "后台 rAF 帧率"))
        throttle_off = probe("去掉防节流组（后台 rAF）", ["--remote-debugging-port=0"],
                             lambda cdp, port, _: (round(raf_fps_when_hidden(cdp), 1), "后台 rAF 帧率"))
        if throttle_on is not None and throttle_on == throttle_off:
            rows.append(["防节流对照结论", "本机不可区分", str(throttle_on),
                         "headless 下页面无真实可见性切换，需 --headful（有 DISPLAY）重测"])

        # 4. --user-data-dir：始终由脚本指定，这里只验证目录确实独立生成
        probe("独立 --user-data-dir", ["--remote-debugging-port=0"],
              lambda cdp, port, data_dir: (str(data_dir.name),
                                           f"profile 独立创建（含 Default/）: "
                                           f"{(data_dir / 'Default').exists()}"))

        # 5. --app（可选）
        if args.with_app:
            has_display = bool(os.environ.get("DISPLAY"))
            if not has_display:
                rows.append(["--app", "n/a", "-", "没有 DISPLAY，headless 下不可测"])
            else:
                probe("--app 模式", ["--remote-debugging-port=0", "--app=" + url],
                      lambda cdp, port, _: (
                          (cdp.eval_json("window.outerWidth") or 0) - (cdp.eval_json("window.innerWidth") or 0),
                          "outerWidth-innerWidth；≈0 表示无浏览器 UI"))
    finally:
        server.shutdown()

    print("\n结果")
    c.print_table(rows, ["场景", "note", "测值", ""])
    print("\n判读：")
    print("  - 有端口文件 = 客户端能连；没有 = 整个方案连不上")
    print("  - devicePixelRatio 必须是 1，否则 1280x720 的坐标与模板全部偏移")
    print("  - 后台 rAF 塌到个位数 = 节流生效，任务在失焦后会卡住")
    evidence.write_json("summary.json", detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
