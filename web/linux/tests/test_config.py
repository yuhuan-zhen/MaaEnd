"""config 的离线回归：默认值拼装、环境变量覆盖、frozen 语义。

跑法：python -m unittest discover -s web/linux/tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maaend_web.config import (
    DEFAULT_CDP_PORT,
    DEFAULT_TIMEOUT,
    TASK_TIMEOUTS,
    load_settings,
)


class SettingsTest(unittest.TestCase):
    """所有用例都传 env 字典，绝不依赖跑测机器上真实的环境变量。"""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "maaend"
        self.root.mkdir()

    def test_dist_wins_over_root(self) -> None:
        env = {"MAAEND_DIST": str(self.root), "MAAEND_ROOT": str(self.tmp / "other")}
        self.assertEqual(load_settings(env).root, self.root)

    def test_root_env_used_when_dist_absent(self) -> None:
        self.assertEqual(load_settings({"MAAEND_ROOT": str(self.root)}).root, self.root)

    def test_root_falls_back_to_home(self) -> None:
        self.assertEqual(load_settings({}).root, Path("~/maaend").expanduser())

    def test_injected_env_hides_os_environ(self) -> None:
        with mock.patch.dict(os.environ, {"MAAEND_DIST": str(self.root)}):
            self.assertEqual(load_settings({}).root, Path("~/maaend").expanduser())

    def test_web_defaults_under_root(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root)})
        self.assertEqual(settings.web, self.root / "web")

    def test_web_override(self) -> None:
        web = self.tmp / "elsewhere" / "web"
        settings = load_settings({"MAAEND_DIST": str(self.root), "MAAEND_WEB": str(web)})
        self.assertEqual(settings.web, web)

    def test_probe_out_is_a_directory_under_web(self) -> None:
        """落盘文件是 <probe_out>/daily_linux_progress.jsonl，与重构前的 OUT_JSONL 同一个路径。"""
        settings = load_settings({"MAAEND_DIST": str(self.root)})
        self.assertEqual(settings.probe_out, self.root / "web" / "probe_out")
        self.assertEqual(
            settings.probe_out / "daily_linux_progress.jsonl",
            self.root / "web" / "probe_out" / "daily_linux_progress.jsonl",
        )

    def test_settings_is_frozen(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root)})
        with self.assertRaises(FrozenInstanceError):
            settings.cdp_port = 1  # type: ignore[misc]


class ResourceDirsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "maaend"
        self.root.mkdir()

    def test_only_existing_dirs_are_kept_in_order(self) -> None:
        (self.root / "resource").mkdir()
        (self.root / "web" / "resource_web").mkdir(parents=True)
        (self.root / "web" / "resource_web_homesrv").mkdir(parents=True)
        settings = load_settings({"MAAEND_DIST": str(self.root)})
        self.assertEqual(
            settings.resource_dirs,
            (
                self.root / "resource",
                self.root / "web" / "resource_web",
                self.root / "web" / "resource_web_homesrv",
            ),
        )

    def test_all_four_layers_when_present(self) -> None:
        for rel in ("resource", "web/resource_web", "web/linux/resource_web_linux", "web/resource_web_homesrv"):
            (self.root / rel).mkdir(parents=True)
        settings = load_settings({"MAAEND_DIST": str(self.root)})
        self.assertEqual(
            settings.resource_dirs,
            (
                self.root / "resource",
                self.root / "web" / "resource_web",
                self.root / "web" / "linux" / "resource_web_linux",
                self.root / "web" / "resource_web_homesrv",
            ),
        )

    def test_empty_when_nothing_exists(self) -> None:
        self.assertEqual(load_settings({"MAAEND_DIST": str(self.root)}).resource_dirs, ())

    def test_explicit_dirs_are_not_filtered(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root), "MAAEND_RES_DIRS": "/a:/b::/c"})
        self.assertEqual(settings.resource_dirs, (Path("/a"), Path("/b"), Path("/c")))

    def test_explicit_dirs_follow_web_override(self) -> None:
        web = self.tmp / "custom-web"
        (web / "resource_web").mkdir(parents=True)
        settings = load_settings({"MAAEND_DIST": str(self.root), "MAAEND_WEB": str(web)})
        self.assertEqual(settings.resource_dirs, (web / "resource_web",))


class PortAndAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "maaend"
        self.root.mkdir()

    def test_cdp_port_default(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root)})
        self.assertEqual(settings.cdp_port, DEFAULT_CDP_PORT)
        self.assertEqual(DEFAULT_CDP_PORT, 9334)

    def test_cdp_port_override(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root), "MAAEND_WEB_CDP_PORT": "9444"})
        self.assertEqual(settings.cdp_port, 9444)

    def test_cdp_port_garbage_falls_back(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root), "MAAEND_WEB_CDP_PORT": "not-a-port"})
        self.assertEqual(settings.cdp_port, DEFAULT_CDP_PORT)

    def test_log_dir_default_and_override(self) -> None:
        self.assertEqual(load_settings({"MAAEND_DIST": str(self.root)}).log_dir, Path("~/maaend-log").expanduser())
        custom = self.tmp / "logs"
        self.assertEqual(
            load_settings({"MAAEND_DIST": str(self.root), "MAA_LOG_DIR": str(custom)}).log_dir,
            custom,
        )

    def test_agent_defaults(self) -> None:
        settings = load_settings({"MAAEND_DIST": str(self.root)})
        self.assertEqual(settings.agent_bin, self.root / "agent" / "go-service")
        self.assertEqual(settings.agent_lib, self.root / "agent" / "maafw")

    def test_agent_overrides(self) -> None:
        bin_path = self.tmp / "bin" / "go-service"
        lib_path = self.tmp / "lib" / "maafw"
        settings = load_settings(
            {
                "MAAEND_DIST": str(self.root),
                "MAA_AGENT_BIN": str(bin_path),
                "MAA_AGENT_LIB": str(lib_path),
            }
        )
        self.assertEqual(settings.agent_bin, bin_path)
        self.assertEqual(settings.agent_lib, lib_path)

    def test_agent_lib_follows_bin_when_only_bin_given(self) -> None:
        bin_path = self.tmp / "opt" / "go-service"
        settings = load_settings({"MAAEND_DIST": str(self.root), "MAA_AGENT_BIN": str(bin_path)})
        self.assertEqual(settings.agent_lib, self.tmp / "opt" / "maafw")


class WlrSocketTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_explicit_socket_wins(self) -> None:
        self.assertEqual(load_settings({"WLR_SOCKET": "/tmp/wayland-9"}).wlr_socket, "/tmp/wayland-9")

    def test_existing_socket_found_via_xdg_runtime_dir(self) -> None:
        sock = self.tmp / "wayland-1"
        sock.write_text("", encoding="utf-8")
        settings = load_settings({"XDG_RUNTIME_DIR": str(self.tmp)})
        self.assertEqual(settings.wlr_socket, str(sock))

    def test_socket_is_always_a_non_empty_string(self) -> None:
        self.assertTrue(load_settings({}).wlr_socket)


class ConstantsTest(unittest.TestCase):
    def test_timeout_table_matches_old_script(self) -> None:
        self.assertEqual(TASK_TIMEOUTS["WebStartGame"], 900)
        self.assertEqual(TASK_TIMEOUTS["AutoCollect"], 2400)
        self.assertEqual(TASK_TIMEOUTS["DeliveryJobs"], 2400)
        self.assertEqual(TASK_TIMEOUTS["ProtocolSpace"], 2400)
        self.assertEqual(TASK_TIMEOUTS["EnvironmentMonitoring"], 900)
        self.assertEqual(len(TASK_TIMEOUTS), 15)

    def test_default_timeout(self) -> None:
        self.assertEqual(DEFAULT_TIMEOUT, 1200)


if __name__ == "__main__":
    unittest.main()
