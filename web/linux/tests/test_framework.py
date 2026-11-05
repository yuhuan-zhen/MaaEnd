"""``maaend_web.framework`` 的离线回归：不装 MaaFramework 也能跑，所有框架交互都打桩。

框架本体在这里是假的（``sys.modules`` 注入几个类），测的是「我们怎么用它」：
控制器参数、agent 环境变量、失败回落、收尾语义。真实的帧/输入由 homesrv 实机验证。

跑法：``python -m unittest discover -s web/linux/tests -v``（在仓库根）。
"""

import json
import os
import subprocess
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
    """没有 maa 时的行为：import 本模块不拉框架，预加载路径静默跳过。"""

    def test_import_does_not_pull_maa(self) -> None:
        """在干净子进程里 import framework，确认没有把 maa 拉进来。

        不能在本进程断言：``unittest discover`` 会先导入其它测试模块，
        其中会碰真 maa（config 的默认参数探测），把它留在 ``sys.modules`` 里。
        测的是「import 本身不拉框架」这个契约，所以必须换一个干净解释器。
        """
        pkg_dir = Path(__file__).resolve().parent.parent
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(pkg_dir)!r}); "
            "import maaend_web.framework; "
            "sys.exit(0 if 'maa' not in sys.modules else 3)"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"maa 被提前导入：{proc.stderr[-400:]}")

    def test_control_unit_so_is_none_without_framework(self) -> None:
        with (
            mock.patch.object(framework.sys, "platform", "linux"),
            mock.patch.dict(sys.modules, {"maa": None}),
        ):
            self.assertIsNone(framework._control_unit_so())

    def test_control_unit_so_is_none_off_linux(self) -> None:
        """非 Linux：这个 DSO 不存在，返回 None 而不是报错。"""
        with mock.patch.object(framework.sys, "platform", "win32"):
            self.assertIsNone(framework._control_unit_so())


class RelativeMoveSupportTest(unittest.TestCase):
    """控制单元预加载：多态区分 + 不重启进程（相对 move/scroll 的前提）。"""

    def setUp(self) -> None:
        framework._control_unit_ready = False
        self.addCleanup(setattr, framework, "_control_unit_ready", False)

    def test_no_framework_is_silent(self) -> None:
        """没装 maa：不适用，静默跳过。"""
        with mock.patch.object(framework, "_control_unit_so", return_value=None):
            framework.ensure_relative_move_support(log=lambda _m: None)

    def test_ld_preload_short_circuits(self) -> None:
        """部署层已设 LD_PRELOAD：跳过，不重复加载。"""
        with (
            mock.patch.object(framework.sys, "platform", "linux"),
            mock.patch.dict(os.environ, {"LD_PRELOAD": "/opt/maa/lib/libMaaLinuxControlUnit.so"}),
            mock.patch.object(framework.ctypes, "CDLL") as cdll,
        ):
            framework.ensure_relative_move_support(log=lambda _m: None)
        cdll.assert_not_called()

    def test_loads_with_rtld_global(self) -> None:
        """正常路径：CDLL 且 mode 含 RTLD_GLOBAL，且不调用 execv（不重启进程）。"""
        so = Path("/opt/maa/lib/libMaaLinuxControlUnit.so")
        with (
            mock.patch.object(framework, "_control_unit_so", return_value=so),
            mock.patch.dict(os.environ, {"LD_PRELOAD": ""}),
            mock.patch.object(framework.sys, "platform", "linux"),
            mock.patch.object(framework.ctypes, "CDLL") as cdll,
            mock.patch.object(framework.os, "execv") as execv,
        ):
            framework.ensure_relative_move_support(log=lambda _m: None)
        cdll.assert_called_once()
        self.assertEqual(cdll.call_args.kwargs["mode"], framework._RTLD_FLAGS)
        execv.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux", "RTLD_* 只在 POSIX 上存在")
    def test_rtld_flags_are_global_and_now(self) -> None:
        """确认标志是 RTLD_GLOBAL|RTLD_NOW，不能少了 NOW 退化成 LAZY。

        不能写 ``ctypes.RTLD_NOW``：ctypes 没导出这个常量（只在内部 DEFAULT_MODE
        里用），Linux 上访问它会 AttributeError。数值是 POSIX 固定的：GLOBAL=0x100，
        NOW=0x2（glibc 与 musl 一致）。
        """
        self.assertEqual(framework._RTLD_FLAGS, 0x100 | 0x2)

    def test_idempotent(self) -> None:
        so = Path("/opt/maa/lib/libMaaLinuxControlUnit.so")
        with (
            mock.patch.object(framework, "_control_unit_so", return_value=so),
            mock.patch.dict(os.environ, {"LD_PRELOAD": ""}),
            mock.patch.object(framework.sys, "platform", "linux"),
            mock.patch.object(framework.ctypes, "CDLL") as cdll,
        ):
            framework.ensure_relative_move_support(log=lambda _m: None)
            framework.ensure_relative_move_support(log=lambda _m: None)
        cdll.assert_called_once()

    def test_cdll_failure_raises(self) -> None:
        """加载失败不能装没事：抛错，让调用方停下。"""
        so = Path("/x/libMaaLinuxControlUnit.so")
        with (
            mock.patch.object(framework, "_control_unit_so", return_value=so),
            mock.patch.dict(os.environ, {"LD_PRELOAD": ""}),
            mock.patch.object(framework.sys, "platform", "linux"),
            mock.patch.object(framework.ctypes, "CDLL", side_effect=OSError("boom")),
            self.assertRaises(framework.ControlUnitLoadError),
        ):
            framework.ensure_relative_move_support(log=lambda _m: None)

    def test_control_unit_so_raises_when_dso_missing(self) -> None:
        """装了 maa 但缺 DSO：必须响亮失败（静默降级会让人以为是能力不支持）。"""
        fake_maa = types.ModuleType("maa")
        fake_maa.__file__ = "/nonexistent/maa/__init__.py"
        with (
            mock.patch.object(framework.sys, "platform", "linux"),
            mock.patch.dict(sys.modules, {"maa": fake_maa}),
            self.assertRaises(framework.ControlUnitLoadError),
        ):
            framework._control_unit_so()

    def test_deprecated_alias_forwards(self) -> None:
        """旧入口 ensure_preload 仍然可用（外部脚本还在用）。"""
        with mock.patch.object(framework, "ensure_relative_move_support") as impl:
            framework.ensure_preload(log=lambda _m: None)
        impl.assert_called_once()


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
