"""恢复层：把游戏拉回可操作状态（节点恢复链 / 硬重置 / 失败现场帧）。

这些动作用来兜底「云会话掉回落地页、子场景退不出来、领奖弹窗挡住画面」这类
网页端才会有的故障；纯 pipeline 里没有等价节点，所以放在 Python 侧。

层级：runtime（碰 ``maa``，但所有导入都在函数体内，可离线单测）。

用法::

    rec = Recoverer(tasker, ctrl, settings, log)
    if not rec.in_world():
        rec.recover("[前置]")
"""

import contextlib
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from maaend_web.config import Settings

Log = Callable[[str], None]

# 启动判据：只有看到启动按钮 / 标题页「点击任意位置继续」才说明没进游戏
START_NODES = ("WebLauncherStartButton", "WebTitleContinue")
# 进了大世界的判据（上游 pipeline 里已有的识别节点）
IN_WORLD_NODE = "WebAlreadyInGame"
# 恢复节点链：领奖弹窗 -> 月卡 -> 结束拜访 -> 退出世界空间（确认/执行）
RESUME_CHAIN = (
    "WebCloseRewards",
    "WebMonthlyCard",
    "__ScenePrivateEndVisit",
    "__ScenePrivateWorldSpaceExitConfirm",
    "__ScenePrivateWorldSpaceExit",
)
RESUME_CAP = 25  # 单个恢复节点的上限（秒）：恢复节点本身就是几次点击，给 25s 足够
START_NODE = "WebStartGameEntry"
START_CAP = 900  # 从落地页点进游戏可能要走排队/加载，给 900s
RESET_URL = "https://endfield.hypergryph.com/cloud"
RESET_WAIT = 12
RESET_TIMEOUT = 90


class Recoverer:
    """把「现在能不能继续跑任务」的判断与恢复动作收在一起。

    调用方只需要 `recover()` / `in_world()` / `needs_start()`；节点链、硬重置、
    失败现场帧的实现都留在这里，方便单点修改。
    """

    def __init__(self, tasker: Any, ctrl: Any, settings: Settings, log: Log = print) -> None:
        self.tasker = tasker
        self.ctrl = ctrl
        self.settings = settings
        self.log = log

    # ------------------------------------------------------------------ 判据
    def in_world(self) -> bool:
        """当前是否在大世界/可操作菜单里。"""
        return self._hit((IN_WORLD_NODE,))

    def needs_start(self) -> bool:
        """判断是否还在启动页/标题页，需要先点开始。

        不用 InWorld/InMenuList 做正向判据：在好友列表这类子菜单里两者都为 False，
        会把「已在游戏内的某个菜单」误判成「没进游戏」，导致反复跑 WebStartGame。
        改为反向判据：只有看到启动按钮或标题页「点击任意位置继续」才需要启动。
        """
        return self._hit(START_NODES)

    def _hit(self, nodes: tuple[str, ...]) -> bool:
        """在当前帧上跑一次 And 识别，任一节点命中就返回 True。

        判定必须看 `get_node_detail().recognition.hit`，不能只看 node_id_list 是否
        非空：And 识别会为每个子节点生成一条 node 记录，没命中也在列表里。
        """
        from maa.pipeline import JAnd, JRecognitionType

        try:
            self.ctrl.post_screencap().wait()
            img = self.ctrl.cached_image
        except Exception as e:  # 截图失败（CDP 断开/合成器没了）不该把整批任务炸掉
            self.log(f"    (截图失败，按未命中处理: {str(e)[:60]})")
            return False
        if img is None:
            return False
        try:
            job = self.tasker.post_recognition(JRecognitionType.And, JAnd(all_of=list(nodes)), img)
            job.wait()
            detail = job.get()
        except Exception as e:
            self.log(f"    (识别提交失败: {str(e)[:60]})")
            return False
        for nid in list(getattr(detail, "node_id_list", None) or []):
            reco = getattr(self.tasker.get_node_detail(int(nid)), "recognition", None)
            if reco is not None and getattr(reco, "hit", False):
                return True
        return False

    # ------------------------------------------------------------------ 动作
    def run_node(self, node: str, cap: int = 90) -> bool:
        """跑一个节点（当作 entry），返回是否 succeeded。"""
        try:
            job = self.tasker.post_task(node)
        except Exception as e:
            self.log(f"    (恢复节点 {node} 提交失败: {e})")
            return False
        t0 = time.time()
        while not job.done and time.time() - t0 < cap:
            time.sleep(1)
        if not job.done:
            with contextlib.suppress(Exception):
                self.tasker.post_stop().wait()  # 超时必须停，否则后面的识别都抢不到控制器
            return False
        return bool(job.succeeded)

    def recover(self, tag: str = "") -> bool:
        """把游戏拉回可操作状态：先试「领奖弹窗/月卡/结束拜访/退出世界」，再硬重置重开。

        节点链的顺序不能换：领奖弹窗和月卡是模态框，不关掉后面的点击全打在弹窗上；
        结束拜访必须早于退出世界空间，否则退到一半又被打断。
        """
        if self.in_world():
            return True
        self.log(f"  ! {tag + ' ' if tag else ''}当前不在大世界/菜单，尝试恢复")
        for node in RESUME_CHAIN:
            if self.in_world():
                break
            ok = self.run_node(node, cap=RESUME_CAP)
            self.log(f"    恢复节点 {node:<34} -> {ok}")
            if self.in_world():
                break
        if self.in_world():
            return True
        if self.needs_start():
            self.log("    页面在启动页/标题页，重跑 WebStartGame")
            if self.run_node(START_NODE, cap=START_CAP) and self.in_world():
                return True
            return self.in_world()
        return self.hard_reset(tag) or self.in_world()

    def hard_reset(self, tag: str = "") -> bool:
        """节点恢复全部无效时：直接重置页面回启动页，再重新进游戏。

        拜访空间、协议空间这类子场景里 InWorld 不命中，靠 ESC/退出节点未必能出来；
        重置页面是确定性的，代价约 60~90 秒，比在子场景里反复空转便宜。
        """
        self.log(f"    {tag + ' ' if tag else ''}硬重置：页面回启动页并重新进游戏")
        try:
            # 解释器用 sys.executable：cron 里的 PATH 不一定有 python3，而 reset_page.py
            # 只用标准库，跟着当前解释器跑最稳。
            subprocess.run(
                [
                    sys.executable or "python3",
                    str(self._reset_script()),
                    "--port",
                    str(self.settings.cdp_port),
                    "--url",
                    RESET_URL,
                    "--wait",
                    str(RESET_WAIT),
                ],
                timeout=RESET_TIMEOUT,
                capture_output=True,
            )
        except Exception as e:
            self.log(f"    (重置页面失败: {str(e)[:60]})")
        return self.run_node(START_NODE, cap=START_CAP) and self.in_world()

    def _reset_script(self) -> Path:
        """reset_page.py 的位置：优先 MAAEND_WEB/linux，其次包目录的兄弟（源码树布局）。"""
        for cand in (
            Path(self.settings.web) / "linux" / "reset_page.py",
            Path(__file__).resolve().parents[1] / "reset_page.py",
        ):
            if cand.exists():
                return cand
        return Path(__file__).resolve().parents[1] / "reset_page.py"

    def save_failshot(self, tag: str) -> None:
        """失败现场留一帧：<log_dir>/failshots/<日期>/<时间>-<tag>.png

        只读操作（多抓一帧），不改任何游戏状态。用于事后看「到底卡在哪个界面」，
        也是发现新 UI（签到页/活动中心这类）唯一可靠的来源。
        """
        try:
            from PIL import Image
        except Exception:  # PIL 是可选依赖：没装就静默跳过
            return
        try:
            self.ctrl.post_screencap().wait()
            img = self.ctrl.cached_image
            if img is None:
                return
            day = Path(self.settings.log_dir) / "failshots" / time.strftime("%Y-%m-%d")
            day.mkdir(parents=True, exist_ok=True)
            path = day / f"{time.strftime('%H%M%S')}-{tag}.png"
            Image.fromarray(img[:, :, ::-1]).save(str(path))  # 框架给的是 BGR
            self.log(f"    [failshot] {path}")
        except Exception as e:
            self.log(f"    (failshot 失败: {str(e)[:60]})")
