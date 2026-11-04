"""``maaend_web.overlay`` 的纯函数回归（不连浏览器）。

移植自上游 ``web/linux/tests/test_overlay_ctl.py``（``feat/web-linux-layer`` @ 470d64432），
用例与断言逐字保留，只改 import：``overlay_ctl`` → ``maaend_web.overlay``。真实 CDP 通路
由 homesrv 上的 ``--once`` / ``--check`` 验证；这里锁筛选、注入顺序、判读与退出码。

后面四个类是本仓库新增的（合并了两条线，总得有东西盯着）：

- ``PolicyCommandsTest``：策略注入序列与 ``--no-policy``；
- ``FingerprintDriftTest``：外露的 class 指纹必须还在 ``page_js.FLATTEN_JS`` 里；
- ``SelfHealTest``：``_probe_or_reinject`` 的注入/自愈分支；
- ``ExitCodeTest``：``run_check`` 的 0/1/2 与 CLI 的 ``--port`` 翻译。

跑法：``python -m unittest tests.test_overlay_ctl -v``（在 ``web/linux`` 下）。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import page_js
from maaend_web import overlay as overlay_ctl
from maaend_web.cli import overlay as overlay_cli


def page(tid: str, url: str, type_: str = "page") -> dict[str, Any]:
    return {
        "id": tid,
        "type": type_,
        "url": url,
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9334/devtools/page/{tid}",
    }


class SelectTargetsTest(unittest.TestCase):
    def test_only_endfield_pages(self):
        pages = [
            page("a", "https://game.example/endfield/index.html"),
            page("b", "https://other.example/landing"),
            page("c", "https://game.example/endfield/index.html", type_="iframe"),
            {"id": "d", "type": "page", "url": "https://game.example/endfield/"},
        ]
        picked = overlay_ctl.select_targets(pages)
        self.assertEqual([t["id"] for t in picked], ["a"])

    def test_empty_hint_keeps_all_pages(self):
        pages = [page("a", "https://x/endfield"), page("b", "https://x/other")]
        self.assertEqual([t["id"] for t in overlay_ctl.select_targets(pages, "")], ["a", "b"])

    def test_case_insensitive_hint(self):
        pages = [page("a", "https://x/EndField/play")]
        self.assertEqual(len(overlay_ctl.select_targets(pages, "endfield")), 1)


class InjectCommandsTest(unittest.TestCase):
    def test_order_and_payload(self):
        cmds = overlay_ctl.inject_commands()
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[0][0], "Page.addScriptToEvaluateOnNewDocument")
        self.assertEqual(cmds[0][1]["source"], page_js.FLATTEN_JS)
        self.assertEqual(cmds[1][0], "Runtime.evaluate")
        self.assertEqual(cmds[1][1]["expression"], page_js.FLATTEN_JS)


class SummarizeTest(unittest.TestCase):
    def probe(self):
        return {
            "version": "linux-2",
            "ball": [{"shown": False}],
            "ping": [
                {"text": "9ms", "hiddenByFlatten": True, "shown": False},
                {"text": "23 ms", "hiddenByFlatten": False, "shown": True},
            ],
            "geo": [],
            "counter": {"ball": 1, "ping": 2, "geo": 0, "version": "linux-2"},
        }

    def test_counts(self):
        s = overlay_ctl.summarize(self.probe())
        self.assertEqual((s["ball"], s["ping"], s["geo"], s["hidden"]), (1, 2, 0, 1))
        self.assertEqual(s["version"], "linux-2")
        self.assertEqual(s["counter"]["ping"], 2)

    def test_hidden_counts_css_hidden_too(self):
        """CSS 先藏掉时 JS 不会打 marker，hidden 必须按「当前不可见」计。"""
        probe = {
            "ping": [{"text": "7ms", "hiddenByFlatten": False, "shown": False, "lifted": 0}],
            "ball": [],
            "geo": [],
            "counter": {"ping": 0},
        }
        self.assertEqual(overlay_ctl.summarize(probe)["hidden"], 1)

    def test_all_hidden(self):
        self.assertFalse(overlay_ctl.all_hidden(self.probe()))
        hidden = {"ping": [{"hiddenByFlatten": True, "shown": False}]}
        self.assertTrue(overlay_ctl.all_hidden(hidden))
        self.assertTrue(overlay_ctl.all_hidden({"ping": []}), "没有浮层也算已处理")


class NeedsReinjectTest(unittest.TestCase):
    def test_missing_counter_means_reinject(self):
        # 2026-11-02 真实会话复现：文档被替换后 counter 消失，浮层还可见
        self.assertTrue(overlay_ctl.needs_reinject({"counter": None, "ping": [{"shown": True}]}))

    def test_visible_ping_means_reinject(self):
        self.assertTrue(overlay_ctl.needs_reinject({"counter": {"version": "linux-2"}, "ping": [{"shown": True}]}))

    def test_injected_and_hidden_is_stable(self):
        self.assertFalse(overlay_ctl.needs_reinject({"counter": {"version": "linux-2"}, "ping": [{"shown": False}]}))
        self.assertFalse(overlay_ctl.needs_reinject({"counter": {"version": "linux-2"}, "ping": []}))


class SessProbeShapeTest(unittest.TestCase):
    """Sess.probe 只依赖 ev()，用假会话锁「返回 dict」这一契约。"""

    def test_probe_parses_json(self):
        class FakeSess(overlay_ctl.Sess):
            def __init__(self):
                pass

            def ev(self, expr):
                self.expr = expr
                return json.dumps({"version": "linux-2", "ping": [], "geo": []})

        sess = FakeSess()
        out = sess.probe()
        self.assertEqual(out["version"], "linux-2")
        self.assertEqual(sess.expr, page_js.PROBE_JS)


class PolicyCommandsTest(unittest.TestCase):
    """策略注入：与抹平同序（先 addScript 再 evaluate），且不污染 ``inject_commands`` 的两条契约。"""

    def test_policy_commands_shape(self):
        cmds = overlay_ctl.policy_commands("(() => {})();")
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[0][0], overlay_ctl.INJECT_METHOD)
        self.assertEqual(cmds[0][1]["source"], "(() => {})();")
        self.assertEqual(cmds[1][0], overlay_ctl.EVAL_METHOD)
        self.assertEqual(cmds[1][1]["expression"], "(() => {})();")

    def test_no_policy_source_means_no_commands(self):
        self.assertEqual(overlay_ctl.policy_commands(""), [])
        with mock.patch.object(overlay_ctl, "policy_candidates", return_value=[]):
            self.assertEqual(overlay_ctl.policy_commands(), [])

    def test_overlay_commands_order(self):
        cmds = overlay_ctl.overlay_commands()
        self.assertEqual(cmds[-2:], overlay_ctl.inject_commands(), "抹平必须在最后两条")
        if overlay_ctl.policy_source():
            self.assertEqual(len(cmds), 4, "有策略文件时应是 策略两连 + 抹平两连")
            self.assertEqual(cmds[0][1]["source"], overlay_ctl.policy_source())
        else:
            self.assertEqual(len(cmds), 2)

    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {"MAAEND_CLOUD_POLICY": "D:/nowhere/policy.js"}):
            self.assertEqual(overlay_ctl.policy_candidates()[0], Path("D:/nowhere/policy.js"))

    def test_missing_file_reads_empty(self):
        with mock.patch.object(overlay_ctl, "policy_path", return_value=None):
            self.assertEqual(overlay_ctl.policy_source(), "")


class FingerprintDriftTest(unittest.TestCase):
    """合并后 class 指纹有两处：本模块的常量（日志/文档）与 FLATTEN_JS 的实现。必须一致。"""

    def test_selectors_present_in_flatten_js(self):
        for sel in (*overlay_ctl.BALL_SELECTORS, *overlay_ctl.PING_SELECTORS):
            self.assertIn(sel, page_js.FLATTEN_JS, f"{sel} 不在 page_js.FLATTEN_JS 里，改版后没同步")

    def test_fingerprint_lists_both(self):
        fp = overlay_ctl.overlay_fingerprint()
        self.assertEqual(len(fp["ball"]), 2)
        self.assertEqual(len(fp["ping"]), 2)


class SelfHealTest(unittest.TestCase):
    """``_probe_or_reinject``：新连上就注入，判到失效就重注入，稳定时只 probe。"""

    class Rec:
        def __init__(self, probes):
            self.probes = list(probes)
            self.methods = []

        def call(self, method, **params):
            self.methods.append(method)
            return {}

        def probe(self):
            return self.probes.pop(0) if len(self.probes) > 1 else self.probes[0]

    def test_force_injects(self):
        sess = self.Rec([{"counter": {"version": "linux-2"}, "ping": []}])
        probe, action = overlay_ctl._probe_or_reinject(sess, force=True, policy=False)
        self.assertEqual(action, "injected")
        self.assertEqual(sess.methods, [overlay_ctl.INJECT_METHOD, overlay_ctl.EVAL_METHOD])
        self.assertEqual(probe["counter"]["version"], "linux-2")

    def test_document_replaced_reinjects(self):
        sess = self.Rec([{"counter": None, "ping": [{"shown": True}]}, {"counter": {"version": "linux-2"}, "ping": []}])
        probe, action = overlay_ctl._probe_or_reinject(sess, force=False, policy=False)
        self.assertEqual(action, "reinjected")
        self.assertEqual(len(sess.methods), 2, "重注入只该发抹平两条（policy=False）")
        self.assertFalse(overlay_ctl.needs_reinject(probe))

    def test_stable_only_probes(self):
        sess = self.Rec([{"counter": {"version": "linux-2"}, "ping": [{"shown": False}]}])
        _, action = overlay_ctl._probe_or_reinject(sess, force=False, policy=False)
        self.assertEqual(action, "probe")
        self.assertEqual(sess.methods, [])


class ExitCodeTest(unittest.TestCase):
    """退出码契约：全隐藏=0 / 有残留=1 / 连不上或无 target=2（含 run_check 与 CLI 的翻译）。"""

    class ProbeSess:
        def __init__(self, probe, url=""):
            self._probe = probe
            self.url = url
            self.closed = False

        def probe(self):
            return self._probe

        def close(self):
            self.closed = True

    def _run_check(self, probe, targets=None):
        sess = self.ProbeSess(probe)
        with (
            mock.patch.object(overlay_ctl, "list_pages", return_value=targets or [page("a", "https://x/endfield")]),
            mock.patch.object(overlay_ctl, "Sess", return_value=sess),
            mock.patch.object(overlay_ctl, "_log", lambda _m: None),
        ):
            code = overlay_ctl.run_check("http://127.0.0.1:9334", "endfield")
        self.assertTrue(sess.closed, "run_check 必须关连接")
        return code

    def test_all_hidden_is_zero(self):
        self.assertEqual(self._run_check({"version": "linux-2", "ping": [{"hiddenByFlatten": True, "shown": False}]}), 0)

    def test_residual_is_one(self):
        self.assertEqual(self._run_check({"version": "linux-2", "ping": [{"hiddenByFlatten": False, "shown": True}]}), 1)

    def test_unreachable_is_two(self):
        with (
            mock.patch.object(overlay_ctl, "list_pages", side_effect=urllib.error.URLError("refused")),
            mock.patch.object(overlay_ctl, "_log", lambda _m: None),
        ):
            self.assertEqual(overlay_ctl.run_check("http://127.0.0.1:1", "endfield"), 2)

    def test_no_target_is_two(self):
        with (
            mock.patch.object(overlay_ctl, "list_pages", return_value=[page("b", "https://x/other")]),
            mock.patch.object(overlay_ctl, "_log", lambda _m: None),
        ):
            self.assertEqual(overlay_ctl.run_check("http://127.0.0.1:9334", "endfield"), 2)

    def test_cli_port_becomes_devtools_url(self):
        with mock.patch.object(overlay_ctl, "run_check", return_value=0) as run:
            self.assertEqual(overlay_cli.main(["--check", "--port", "9444"]), 0)
        run.assert_called_once_with("http://127.0.0.1:9444", "endfield")

    def test_cli_without_action_is_two(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(overlay_cli.main([]), 2)
        self.assertIn("--check", out.getvalue(), "没给动作时应该打 help")

    def test_cli_no_policy_flag(self):
        with mock.patch.object(overlay_ctl, "run_once", return_value=0) as run:
            self.assertEqual(overlay_cli.main(["--once", "--no-policy"]), 0)
        self.assertFalse(run.call_args.kwargs["policy"])


if __name__ == "__main__":
    unittest.main()
