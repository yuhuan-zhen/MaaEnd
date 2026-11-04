"""``maaend_web.framework`` 的离线回归：不装 MaaFramework 也能跑，所有框架交互都打桩。

框架本体在这里是假的（``sys.modules`` 注入几个类），测的是「我们怎么用它」：
控制器参数、agent 环境变量、失败回落、收尾语义。真实的帧/输入由 homesrv 实机验证。

跑法：``python -m unittest discover -s web/linux/tests -v``（在仓库根）。
"""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from maaend_web import framework
from maaend_web.config import load_settings


def fake_modules(name: str, **attrs) -> dict:
    """造一个 ``sys.modules`` 补丁字典：``name`` 包 + 属性。"""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return {name: mod}


class NoFrameworkTest(unittest.TestCase):
    """没有 maa 时的行为：import 本模块不拉框架，preload 静默跳过。"""

    def test_import_does_not_pull_maa(self) -> None:
        self.assertNotIn("maa", sys.modules)

    def test_preload_so_is_none_without_framework(self) -> None:
        self.assertIsNone(framework._preload_so())

    def test_ensure_preload_is_noop_without_framework(self) -> None:
        with mock.patch.object(framework.os, "execv") as execv:
            framework.ensure_preload(log=lambda _m: None)
        execv.assert_not_called()


class EnsurePreloadTest(unittest.TestCase):
    """有控制单元 DSO 时：补 LD_PRELOAD 并重新 exec 自己（否则 relative_move 失效）。"""

    def test_sets_preload_and_reexecs(self) -> None:
        with (
            mock.patch.object(framework, "_preload_so", return_value="/opt/maa/lib/libMaaLinuxControlUnit.so"),
            mock.patch.dict(os.environ, {"LD_PRELOAD": ""}),
            mock.patch.object(framework.os, "execv") as execv,
        ):
            framework.ensure_preload(log=lambda _m: None)
            self.assertEqual(os.environ["LD_PRELOAD"], "/opt/maa/lib/libMaaLinuxControlUnit.so")
        execv.assert_called_once()
        self.assertEqual(execv.call_args[0][0], sys.executable)

    def test_keeps_existing_preload(self) -> None:
        with (
            mock.patch.object(framework, "_preload_so", return_value="/opt/lib/libMaaLinuxControlUnit.so"),
            mock.patch.dict(os.environ, {"LD_PRELOAD": "/usr/lib/libfoo.so"}),
            mock.patch.object(framework.os, "execv") as execv,
        ):
            framework.ensure_preload(log=lambda _m: None)
            self.assertEqual(
                os.environ["LD_PRELOAD"],
                "/opt/lib/libMaaLinuxControlUnit.so:/usr/lib/libfoo.so",
            )
        execv.assert_called_once()

    def test_skips_when_already_loaded(self) -> None:
        with (
            mock.patch.object(framework, "_preload_so", return_value="/opt/lib/libMaaLinuxControlUnit.so"),
            mock.patch.dict(os.environ, {"LD_PRELOAD": "/opt/lib/libMaaLinuxControlUnit.so"}),
            mock.patch.object(framework.os, "execv") as execv,
        ):
            framework.ensure_preload(log=lambda _m: None)
        execv.assert_not_called()


class SocketTest(unittest.TestCase):
    def test_find_wlr_socket_forwards_env(self) -> None:
        # 探测逻辑在 config（单一真源），framework 只转发。
        self.assertEqual(framework.find_wlr_socket({"WLR_SOCKET": "/tmp/xdg-run/wayland-9"}), "/tmp/xdg-run/wayland-9")


class MakeControllerTest(unittest.TestCase):
    """控制器参数是行为契约：键名/取值写错，游戏里就是「点了没反应」。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = load_settings({"MAAEND_DIST": self.tmp.name, "WLR_SOCKET": "/tmp/xdg-run/wayland-1"})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_wlroots_uses_linux_controller_with_expected_params(self) -> None:
        seen = {}

        class FakeLinux:
            def __init__(self, params):
                seen.update(params)

        class Boom:  # 不该被用到
            def __init__(self, *a, **kw):
                raise AssertionError("LinuxController 成功时不应回落到 WlRootsController")

        mods = fake_modules("maa.controller", LinuxController=FakeLinux, WlRootsController=Boom)
        with mock.patch.dict(sys.modules, mods):
            ctrl = framework.make_controller(framework.CONTROLLER_WLROOTS, self.settings, log=lambda _m: None)
        self.assertIsInstance(ctrl, FakeLinux)
        self.assertEqual(seen["screencap_method"], 1)
        self.assertEqual(seen["input_method"], 1)
        self.assertEqual(seen["wlr_socket_path"], "/tmp/xdg-run/wayland-1")
        self.assertIs(seen["use_win32_vk_code"], True)

    def test_wlroots_falls_back_to_legacy_controller(self) -> None:
        logs: list[str] = []

        class Boom:
            def __init__(self, params):
                raise RuntimeError("socket 不存在")

        class Legacy:
            def __init__(self, sock, use_win32_vk_code=False):
                self.sock, self.vk = sock, use_win32_vk_code

        mods = fake_modules("maa.controller", LinuxController=Boom, WlRootsController=Legacy)
        with mock.patch.dict(sys.modules, mods):
            ctrl = framework.make_controller(framework.CONTROLLER_WLROOTS, self.settings, log=logs.append)
        self.assertIsInstance(ctrl, Legacy)
        self.assertEqual(ctrl.sock, "/tmp/xdg-run/wayland-1")
        self.assertIs(ctrl.vk, True)
        self.assertTrue(any("回落" in line for line in logs))

    def test_cdp_controller_lives_in_devtools(self) -> None:
        seen = {}

        def make_custom_controller(**kw):
            seen.update(kw)
            return "cdp-controller"

        with mock.patch.dict(sys.modules, fake_modules("devtools.cdp", make_custom_controller=make_custom_controller)):
            ctrl = framework.make_controller(framework.CONTROLLER_CDP, self.settings, log=lambda _m: None)
        self.assertEqual(ctrl, "cdp-controller")
        self.assertEqual(seen["port"], self.settings.cdp_port)


class PiEnvTest(unittest.TestCase):
    """agent 靠 PI_* 环境变量知道「接哪个控制器、加载哪些资源层」。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "interface.json").write_text('{"version": "v2.35.0", "interfaceVersion": 2}', encoding="utf-8")
        self.settings = load_settings({"MAAEND_DIST": self.tmp.name})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_shape_and_values(self) -> None:
        env = framework._pi_env(self.settings, "Linux-Wlroots", "官服-网页端")
        self.assertEqual(env["PI_CLIENT_NAME"], "MXU")
        self.assertEqual(env["PI_VERSION"], "v2.35.0")
        self.assertEqual(env["PI_CLIENT_VERSION"], "2.35.0")
        self.assertEqual(env["PI_INTERFACE_VERSION"], "2")
        controller = json.loads(env["PI_CONTROLLER"])
        self.assertEqual(controller["name"], "Linux-Wlroots")
        self.assertEqual(controller["type"], "Linux")
        self.assertEqual(controller["linux"]["screencap"], "Wlr")
        resource = json.loads(env["PI_RESOURCE"])
        self.assertEqual(resource["name"], "官服-网页端")
        self.assertEqual(resource["path"], [str(p) for p in self.settings.resource_dirs])

    def test_missing_interface_falls_back(self) -> None:
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        settings = load_settings({"MAAEND_DIST": str(empty)})
        self.assertEqual(framework._pi_versions(settings), ("unknown", "2"))


class StartAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "agent" / "go-service"
        self.bin.parent.mkdir(parents=True)
        self.bin.write_text("", encoding="utf-8")
        self.settings = load_settings(
            {"MAAEND_DIST": self.tmp.name, "MAA_AGENT_BIN": str(self.bin), "MAA_AGENT_LIB": str(self.root / "maafw")}
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_binary_returns_none_pair(self) -> None:
        logs: list[str] = []
        client, proc = framework.start_agent(None, self.settings, bin_path=self.root / "nope", log=logs.append)
        self.assertIsNone(client)
        self.assertIsNone(proc)
        self.assertTrue(any("[X] 找不到 agent" in line for line in logs))

    def test_happy_path_binds_before_connect_and_sets_pi_env(self) -> None:
        order: list[str] = []

        class FakeClient:
            identifier = "abc123"
            alive = True
            custom_action_list: ClassVar[list[str]] = ["A"]
            custom_recognition_list: ClassVar[list[str]] = ["R"]

            def bind(self, res):
                order.append("bind")
                self.res = res
                return True

            def connect(self):
                order.append("connect")
                return True

        fake_client = FakeClient()
        fake_agent_client = types.SimpleNamespace(AgentClient=types.SimpleNamespace(create_tcp=lambda _p: fake_client))
        popen_kwargs = {}

        def fake_popen(argv, **kw):
            order.append("popen")
            popen_kwargs.update(kw)
            popen_kwargs["argv"] = argv
            return types.SimpleNamespace(pid=4242, terminate=lambda: order.append("terminate"))

        mods = fake_modules("maa.agent_client", AgentClient=fake_agent_client.AgentClient)
        with (
            mock.patch.dict(sys.modules, mods),
            mock.patch.object(framework.subprocess, "Popen", side_effect=fake_popen),
        ):
            client, proc = framework.start_agent("res-obj", self.settings, tag="go-service", log=lambda _m: None)

        self.assertIs(client, fake_client)
        self.assertEqual(proc.pid, 4242)
        # 顺序：bind(resource) 必须早于 connect()，否则框架报 "resource is not bound"。
        self.assertLess(order.index("bind"), order.index("connect"))
        self.assertEqual(order[:3], ["bind", "popen", "connect"])
        self.assertEqual(popen_kwargs["argv"], [str(self.bin), "abc123"])
        self.assertIn(str(self.root / "maafw"), popen_kwargs["env"]["LD_LIBRARY_PATH"])
        self.assertIn("PI_CONTROLLER", popen_kwargs["env"])
        self.assertEqual(popen_kwargs["cwd"], str(self.bin.parent))

    def test_start_agents_warns_when_cpp_algo_missing(self) -> None:
        logs: list[str] = []
        seen: list[str] = []

        def fake_start_agent(res, settings, *, bin_path=None, tag=None, **_kw):
            seen.append(bin_path.name if bin_path else "")
            return (None, None)

        with mock.patch.object(framework, "start_agent", side_effect=fake_start_agent):
            framework.start_agents(None, self.settings, log=logs.append)
        self.assertEqual(seen, ["go-service"])
        self.assertTrue(any("缺少 cpp-algo" in line for line in logs))

    def test_start_agents_includes_cpp_algo_when_present(self) -> None:
        (self.bin.parent / framework.CPP_ALGO).mkdir()
        seen: list[str] = []

        def fake_start_agent(res, settings, *, bin_path=None, tag=None, **_kw):
            seen.append(bin_path.name if bin_path else "")
            return (None, None)

        with mock.patch.object(framework, "start_agent", side_effect=fake_start_agent):
            framework.start_agents(None, self.settings, log=lambda _m: None)
        self.assertEqual(seen, ["go-service", "cpp-algo"])


class StopAgentsTest(unittest.TestCase):
    def test_terminates_every_started_agent(self) -> None:
        terminated: list[int] = []

        def proc(pid):
            return types.SimpleNamespace(pid=pid, terminate=lambda: terminated.append(pid))

        framework.stop_agents([(None, proc(1)), (None, None), (None, proc(2))], log=lambda _m: None)
        self.assertEqual(terminated, [1, 2])

    def test_terminate_error_is_swallowed(self) -> None:
        def boom():
            raise ProcessLookupError

        framework.stop_agents([(None, types.SimpleNamespace(pid=7, terminate=boom))], log=lambda _m: None)


class SetupTaskerTest(unittest.TestCase):
    def test_missing_framework_is_logged_not_raised(self) -> None:
        logs: list[str] = []
        settings = load_settings({"MAAEND_DIST": "/nonexistent"})

        class Tasker:
            def set_stdout_level(self, _lvl):
                raise RuntimeError("no maa")

        framework.setup_tasker(Tasker(), settings, log=logs.append)
        self.assertTrue(any("设置日志级别失败" in line for line in logs))

    def test_log_dir_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings({"MAAEND_DIST": "/nonexistent", "MAA_LOG_DIR": str(Path(tmp) / "log")})

            class Tasker:
                level = None
                log_dir = None

                def set_stdout_level(self, lvl):
                    self.level = lvl

                def set_log_dir(self, path):
                    self.log_dir = path

            fake_define = types.SimpleNamespace(LoggingLevelEnum=types.SimpleNamespace(Info=4))
            mods = fake_modules("maa.define", **vars(fake_define))
            tasker = Tasker()
            with mock.patch.dict(sys.modules, mods):
                framework.setup_tasker(tasker, settings, log=lambda _m: None)
            self.assertEqual(tasker.level, 4)
            self.assertTrue(Path(settings.log_dir).is_dir())


if __name__ == "__main__":
    unittest.main()
