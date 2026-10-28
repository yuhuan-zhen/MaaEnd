#!/usr/bin/env python3
"""转向灵敏度标定（通用版，不写死任何机器路径）。

用法：
    python3 calibrate_turn.py [dx] [steps] [gap_s]        # 静止态
    HOLD_KEY=87 python3 calibrate_turn.py 30 8 0.2        # 按住 W（87=VK_W）边走边转

环境变量（都有默认值，按优先级自动探测）：
    MAAEND_ROOT   仓库根（默认：脚本所在目录往上找到含 interface.json 的那层，否则 ~/maaend）
    MAAEND_SOCK   wlr socket（默认 $XDG_RUNTIME_DIR/wayland-1）
    WLR_SOCKET    同上，优先
    MAAEND_RES_DIRS  资源层，冒号分隔（默认按 ROOT 下的标准四层里存在的那些）

做法：用 cpp-algo 的 MapLocateRecognition 读 camRot（小地图箭头=镜头朝向），
每步前后各读一次，Δ 即为这一拖拽转过的角度 → units_per_deg = dx / Δ。
"""
import os
import re
import sys
import time

HOME = os.path.expanduser("~")


def find_root() -> str:
    env = os.environ.get("MAAEND_ROOT") or os.environ.get("MAAEND_DIST")
    if env and os.path.isdir(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for up in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        if os.path.isfile(os.path.join(up, "interface.json")):
            return up
    return os.path.join(HOME, "maaend")


ROOT = find_root()
SOCK = (os.environ.get("WLR_SOCKET") or os.environ.get("MAAEND_SOCK")
        or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "wayland-1"))

for k, v in {
    "MAAEND_DIST": ROOT, "MAAEND_ROOT": ROOT,
    "MAAEND_WEB": os.path.join(ROOT, "web"),
    "MAA_AGENT_BIN": os.path.join(ROOT, "agent", "go-service"),
    "MAA_AGENT_LIB": os.path.join(ROOT, "maafw"),
}.items():
    os.environ.setdefault(k, v)

CANDIDATE_DIRS = [os.path.join(ROOT, p) for p in (
    "resource", "web/resource_web", "web/linux/resource_web_linux", "web/resource_web_homesrv")]
DIRS = [d for d in CANDIDATE_DIRS if os.path.isdir(d)]
os.environ.setdefault("MAAEND_RES_DIRS", ":".join(DIRS))

sys.path.insert(0, os.path.join(ROOT, "web", "linux"))

import run_daily_linux as R  # noqa: E402

R.ensure_preload()

from maa.define import LoggingLevelEnum  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

LOGDIR = os.path.join(HOME, "maaend-calib", time.strftime("%Y%m%d-%H%M%S"))
os.makedirs(LOGDIR, exist_ok=True)
LOG = os.path.join(LOGDIR, "maafw.log")
CAM = re.compile(r'"camRot":([-0-9.]+)')

OV = {"TurnProbe": {"recognition": {"type": "Custom",
                                  "param": {"custom_recognition": "MapLocateRecognition",
                                            "custom_recognition_param": {}}},
                    "action": "DoNothing", "timeout": 15000}}


def log(m):
    print(m, flush=True)


def main():
    dx = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    gap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.20
    hold_key = int(os.environ.get("HOLD_KEY", "0") or 0)

    log("ROOT=%s\nSOCK=%s\nDIRS=%s" % (ROOT, SOCK, DIRS))
    res = Resource()
    for d in DIRS:
        res.post_bundle(d).wait()
    ctrl = R.make_controller(SOCK)
    ctrl.post_connection().wait()
    log("控制器 %s connected=%s" % (type(ctrl).__name__, ctrl.connected))
    if not ctrl.connected:
        return 4
    tasker = Tasker()
    tasker.bind(res, ctrl)
    tasker.set_stdout_level(LoggingLevelEnum.Info)
    tasker.set_log_dir(LOGDIR)
    pairs = R.start_agents(res, "Linux-Wlroots", "官服-网页端")
    time.sleep(1.0)
    for _ in range(2):
        ctrl.post_click_key(27).wait()
        time.sleep(1.5)

    def probe(tag):
        off = os.path.getsize(LOG) if os.path.exists(LOG) else 0
        tasker.post_task("TurnProbe", OV).wait()
        time.sleep(0.2)
        with open(LOG, "rb") as f:
            f.seek(off)
            data = f.read().decode("utf-8", "ignore")
        cams = CAM.findall(data)
        if not cams:
            log("%-10s 无定位" % tag)
            return None
        a = float(cams[-1])
        log("%-10s camRot=%.2f" % (tag, a))
        return a

    a0 = probe("base")
    if a0 is None:
        log("[X] 基准定位失败（先确认在大世界）")
        for p in [p for _c, p in pairs if p]:
            p.terminate()
        return 5

    hold = bool(hold_key) and hasattr(ctrl, "post_key_down")
    if hold_key and not hold:
        log("[!] 控制器没有 post_key_down，退化为静止标定")
    if hold:
        log("按住 VK %d 保持移动" % hold_key)
        ctrl.post_key_down(hold_key).wait()
        time.sleep(0.6)

    prev, total = a0, 0.0
    try:
        log("\n每步 dx=%d，间隔 %.0f ms，共 %d 步" % (dx, gap * 1000, n))
        for i in range(1, n + 1):
            ctrl.post_relative_move(dx, 0).wait()
            time.sleep(gap)
            a = probe("step%02d" % i)
            if a is None:
                break
            d = (a - prev + 180.0) % 360.0 - 180.0
            total += d
            log("           本步 %+.2f°  累计 %+.2f°  (线性预期 %+.2f°/步)" % (d, total, dx / 7.928))
            prev = a
    finally:
        if hold:
            ctrl.post_key_up(hold_key).wait()

    if n:
        avg = total / n
        log("\n[结论] %d 步共 %+.2f°，平均 %+.2f°/步" % (n, total, avg))
        log("        线性预期 %.2f°/步（按 7.93 单位/度）；实测/线性 = %.2f" % (dx / 7.928, avg / (dx / 7.928)))
        if abs(avg) > 0.1:
            log("        折算 %.3f 单位/度；若要改常数 kTurn360UnitsPerWidth = %.4f"
                % (dx / avg, (dx / avg) * 360.0 / 1280.0))
    for p in [p for _c, p in pairs if p]:
        try:
            p.terminate()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
