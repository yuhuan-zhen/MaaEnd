"""``maaend_web.recovery`` 的离线回归：判据、恢复链顺序、硬重置、失败现场帧。

恢复链的顺序是行为契约（弹窗 → 月卡 → 结束拜访 → 退出世界），换顺序会在实机上
「点了没反应」。这里用假的 tasker/ctrl 钉住顺序与分支，真实点击由 homesrv 验证。

跑法：``python -m unittest discover -s web/linux/tests -v``（在仓库根）。
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from maaend_web import recovery
from maaend_web.config import load_settings


class FakeJob:
    """框架 Job 的最小替身：done/succeeded 可由测试控制。"""

    def __init__(self, done=True, succeeded=True):
        self.done = done
        self.succeeded = succeeded
        self.wait_calls = 0

    def wait(self):
        self.wait_calls += 1
        return self


class FakeTasker:
    def __init__(self, jobs=None):
        self.jobs = list(jobs or [])
        self.posted = []
        self.stopped = 0

    def post_task(self, node, override=None):
        self.posted.append(node)
        return self.jobs.pop(0) if self.jobs else FakeJob()

    def post_stop(self):
        self.stopped += 1
        return FakeJob()


class FakeCtrl:
    def __init__(self, image="img", screencap_raises=False):
        self.cached_image = image
        self.screencap_raises = screencap_raises

    def post_screencap(self):
        if self.screencap_raises:
            raise RuntimeError("合成器没了")
        return FakeJob()


class Sliceable:
    """假的 BGR ndarray：只支持 failshot 用到的 ``img[:, :, ::-1]``。"""

    def __getitem__(self, _key):
        return self


def fake_pipeline() -> dict:
    """假的 ``maa.pipeline``：只提供 ``_hit`` 用到的两个名字。"""
    pipeline = types.ModuleType("maa.pipeline")
    pipeline.JAnd = lambda **kw: ("JAnd", kw)
    pipeline.JRecognitionType = types.SimpleNamespace(And="And")
    return {"maa.pipeline": pipeline}


def fake_pil(sink=None):
    """假的 PIL 模块：``Image.fromarray(...).save(path)`` 把路径收进 sink。"""

    class FakeImage:
        @staticmethod
        def fromarray(_arr):
            return types.SimpleNamespace(save=lambda path: sink.append(path) if sink is not None else None)

    pil = types.ModuleType("PIL")
    pil.Image = FakeImage
    return pil


def settings_for(root: Path):
    """临时目录里的 Settings：日志也落在 tmp，不碰运行测试那台机器的 ~/maaend-log。"""
    return load_settings(
        {"MAAEND_DIST": str(root), "MAAEND_WEB": str(root / "web"), "MAA_LOG_DIR": str(root / "log")}
    )


class ConstantsTest(unittest.TestCase):
    def test_resume_chain_order_is_a_contract(self) -> None:
        self.assertEqual(
            recovery.RESUME_CHAIN,
            (
                "WebCloseRewards",
                "WebMonthlyCard",
                "__ScenePrivateEndVisit",
                "__ScenePrivateWorldSpaceExitConfirm",
                "__ScenePrivateWorldSpaceExit",
            ),
        )

    def test_start_nodes_are_reverse_criteria(self) -> None:
        # 反向判据：只有看到启动按钮/标题页提示才算「没进游戏」。
        self.assertEqual(recovery.START_NODES, ("WebLauncherStartButton", "WebTitleContinue"))
        self.assertEqual(recovery.START_NODE, "WebStartGameEntry")
        self.assertEqual(recovery.IN_WORLD_NODE, "WebAlreadyInGame")


class CriteriaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), settings_for(Path(self.tmp.name)), log=lambda _m: None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_in_world_asks_for_one_node(self) -> None:
        with mock.patch.object(self.rec, "_hit", return_value=True) as hit:
            self.assertTrue(self.rec.in_world())
        hit.assert_called_once_with((recovery.IN_WORLD_NODE,))

    def test_needs_start_asks_for_start_nodes(self) -> None:
        with mock.patch.object(self.rec, "_hit", return_value=False) as hit:
            self.assertFalse(self.rec.needs_start())
        hit.assert_called_once_with(recovery.START_NODES)


class HitTest(unittest.TestCase):
    """``_hit`` 必须看 ``recognition.hit``：And 会给每个子节点写一条记录，没命中也存在。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tasker = FakeTasker()
        self.rec = recovery.Recoverer(self.tasker, FakeCtrl(), settings_for(Path(self.tmp.name)), log=lambda _m: None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_screencap_failure_counts_as_miss(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(screencap_raises=True), self.rec.settings, log=lambda _m: None)
        with mock.patch.dict(sys.modules, fake_pipeline()):
            self.assertFalse(rec._hit(("X",)))

    def test_none_image_counts_as_miss(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(image=None), self.rec.settings, log=lambda _m: None)
        with mock.patch.dict(sys.modules, fake_pipeline()):
            self.assertFalse(rec._hit(("X",)))

    def _patch_framework(self, hit_nodes: list[int], hit: bool) -> dict:
        class FakeJob2:
            def wait(self):
                return self

            def get(self):
                return types.SimpleNamespace(node_id_list=hit_nodes)

        class FakeTasker2:
            posts: ClassVar[list] = []

            def post_recognition(self, rtype, param, image):
                FakeTasker2.posts.append((rtype, param, image))
                return FakeJob2()

            def get_node_detail(self, nid):
                return types.SimpleNamespace(recognition=types.SimpleNamespace(hit=hit))

        mods = fake_pipeline()
        self.tasker = FakeTasker2()
        self.rec = recovery.Recoverer(self.tasker, FakeCtrl(), self.rec.settings, log=lambda _m: None)
        return mods, FakeTasker2

    def test_hit_when_recognition_reports_hit(self) -> None:
        mods, tasker_cls = self._patch_framework([11, 12], hit=True)
        with mock.patch.dict(sys.modules, mods):
            self.assertTrue(self.rec._hit(("WebAlreadyInGame",)))
        rtype, param, image = tasker_cls.posts[0]
        self.assertEqual(rtype, "And")
        self.assertEqual(param, ("JAnd", {"all_of": ["WebAlreadyInGame"]}))
        self.assertEqual(image, "img")

    def test_miss_when_recognition_reports_no_hit(self) -> None:
        mods, _tasker_cls = self._patch_framework([11], hit=False)
        with mock.patch.dict(sys.modules, mods):
            self.assertFalse(self.rec._hit(("WebAlreadyInGame",)))

    def test_recognition_exception_counts_as_miss(self) -> None:
        class BoomTasker:
            def post_recognition(self, *a, **kw):
                raise RuntimeError("识别提交失败")

        rec = recovery.Recoverer(BoomTasker(), FakeCtrl(), self.rec.settings, log=lambda _m: None)
        with mock.patch.dict(sys.modules, fake_pipeline()):
            self.assertFalse(rec._hit(("X",)))


class RunNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = settings_for(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_success(self) -> None:
        rec = recovery.Recoverer(FakeTasker([FakeJob(succeeded=True)]), FakeCtrl(), self.settings, log=lambda _m: None)
        self.assertTrue(rec.run_node("WebCloseRewards"))

    def test_failure_without_timeout(self) -> None:
        rec = recovery.Recoverer(FakeTasker([FakeJob(succeeded=False)]), FakeCtrl(), self.settings, log=lambda _m: None)
        self.assertFalse(rec.run_node("WebCloseRewards"))

    def test_submit_exception(self) -> None:
        class Boom:
            def post_task(self, node, override=None):
                raise RuntimeError("tasker 已关")

        rec = recovery.Recoverer(Boom(), FakeCtrl(), self.settings, log=lambda _m: None)
        self.assertFalse(rec.run_node("WebCloseRewards"))

    def test_timeout_stops_the_task(self) -> None:
        # 超时必须 post_stop：框架同一时刻只跑一个 task，不停会把下一个任务卡在 pending。
        tasker = FakeTasker([FakeJob(done=False, succeeded=False)])
        rec = recovery.Recoverer(tasker, FakeCtrl(), self.settings, log=lambda _m: None)
        with mock.patch.object(recovery.time, "sleep"), mock.patch.object(recovery.time, "time", side_effect=[0, 0, 10**6]):
            self.assertFalse(rec.run_node("WebCloseRewards", cap=1))
        self.assertEqual(tasker.stopped, 1)


class RecoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = settings_for(Path(self.tmp.name))
        self.logs: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_in_world_returns_immediately(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), self.settings, log=self.logs.append)
        with mock.patch.object(rec, "in_world", return_value=True), mock.patch.object(rec, "run_node") as run_node:
            self.assertTrue(rec.recover())
        run_node.assert_not_called()

    def test_runs_resume_chain_in_order_until_in_world(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), self.settings, log=self.logs.append)
        order: list[str] = []
        # 跑过 2 个恢复节点后才算回到大世界（recover 每步前后都会问一次 in_world）。
        with (
            mock.patch.object(rec, "in_world", side_effect=lambda: len(order) >= 2),
            mock.patch.object(rec, "run_node", side_effect=lambda node, cap=90: order.append(node) or True),
        ):
            self.assertTrue(rec.recover())
        self.assertEqual(order, ["WebCloseRewards", "WebMonthlyCard"])

    def test_falls_back_to_start_node_when_on_landing(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), self.settings, log=self.logs.append)
        with (
            mock.patch.object(rec, "in_world", return_value=False),
            mock.patch.object(rec, "needs_start", return_value=True),
            mock.patch.object(rec, "run_node", return_value=True) as run_node,
        ):
            self.assertFalse(rec.recover())
        self.assertEqual(run_node.call_args[0][0], recovery.START_NODE)

    def test_falls_back_to_hard_reset(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), self.settings, log=self.logs.append)
        with (
            mock.patch.object(rec, "in_world", return_value=False),
            mock.patch.object(rec, "needs_start", return_value=False),
            mock.patch.object(rec, "run_node", return_value=False),
            mock.patch.object(rec, "hard_reset", return_value=True) as hard_reset,
        ):
            self.assertTrue(rec.recover("[失败后]"))
        hard_reset.assert_called_once_with("[失败后]")


class HardResetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = settings_for(self.root)
        # 生产布局：<root>/web/linux/reset_page.py
        self.script = self.root / "web" / "linux" / "reset_page.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reset_script_prefers_deployed_copy(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), self.settings, log=lambda _m: None)
        self.assertEqual(rec._reset_script(), self.script)

    def test_reset_script_falls_back_to_package_sibling(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root / "elsewhere"), "MAAEND_WEB": str(self.root / "nowhere")})
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), settings, log=lambda _m: None)
        self.assertEqual(rec._reset_script().name, "reset_page.py")

    def test_spawns_reset_script_with_expected_args(self) -> None:
        tasker = FakeTasker([FakeJob(succeeded=True)])
        rec = recovery.Recoverer(tasker, FakeCtrl(), self.settings, log=lambda _m: None)
        with (
            mock.patch.object(recovery.subprocess, "run") as run,
            mock.patch.object(rec, "in_world", return_value=True),
        ):
            self.assertTrue(rec.hard_reset("[启动]"))
        argv = run.call_args[0][0]
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], str(self.script))
        self.assertIn("--url", argv)
        self.assertEqual(argv[argv.index("--url") + 1], recovery.RESET_URL)
        self.assertEqual(argv[argv.index("--port") + 1], str(self.settings.cdp_port))
        self.assertEqual(run.call_args[1]["timeout"], recovery.RESET_TIMEOUT)

    def test_subprocess_failure_is_logged(self) -> None:
        logs: list[str] = []
        rec = recovery.Recoverer(FakeTasker([FakeJob(succeeded=True)]), FakeCtrl(), self.settings, log=logs.append)
        with (
            mock.patch.object(recovery.subprocess, "run", side_effect=OSError("no python")),
            mock.patch.object(rec, "in_world", return_value=True),
        ):
            self.assertTrue(rec.hard_reset())
        self.assertTrue(any("重置页面失败" in line for line in logs))


class FailshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = settings_for(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_skips_silently_without_pillow(self) -> None:
        logs: list[str] = []
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(), self.settings, log=logs.append)
        with mock.patch.dict(sys.modules, {"PIL": None}):
            rec.save_failshot("WebStartGame-att1")
        self.assertEqual(logs, [])

    def test_writes_png_with_date_partition(self) -> None:
        saved: list[str] = []

        pil = fake_pil(saved)
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(image=Sliceable()), self.settings, log=lambda _m: None)
        with mock.patch.dict(sys.modules, {"PIL": pil}):
            rec.save_failshot("WebStartGame-att1")
        self.assertEqual(len(saved), 1)
        path = Path(saved[0])
        self.assertEqual(path.parent.parent.name, "failshots")
        self.assertTrue(path.name.endswith("-WebStartGame-att1.png"))
        self.assertTrue(path.parent.is_dir())

    def test_skips_when_screencap_returns_none(self) -> None:
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(image=None), self.settings, log=lambda _m: None)
        rec.save_failshot("x")  # 不抛即可

    def test_screencap_error_is_swallowed(self) -> None:
        logs: list[str] = []
        rec = recovery.Recoverer(FakeTasker(), FakeCtrl(screencap_raises=True), self.settings, log=logs.append)
        with mock.patch.dict(sys.modules, {"PIL": fake_pil()}):
            rec.save_failshot("x")
        self.assertTrue(any("failshot 失败" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
