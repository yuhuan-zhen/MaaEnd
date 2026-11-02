"""overlay_ctl 的纯函数回归（不连浏览器）。

真实 CDP 通路由 homesrv 上的 ``--once`` / ``--check`` 验证；这里只锁筛选、注入顺序与判读。

跑法：uv run python -m unittest web/linux/tests/test_overlay_ctl.py
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import overlay_ctl
import page_js


def page(tid: str, url: str, type_: str = "page") -> dict[str, Any]:
    return {"id": tid, "type": type_, "url": url, "webSocketDebuggerUrl": f"ws://127.0.0.1:9334/devtools/page/{tid}"}


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

    def test_all_hidden(self):
        self.assertFalse(overlay_ctl.all_hidden(self.probe()))
        hidden = {"ping": [{"hiddenByFlatten": True, "shown": False}]}
        self.assertTrue(overlay_ctl.all_hidden(hidden))
        self.assertTrue(overlay_ctl.all_hidden({"ping": []}), "没有浮层也算已处理")


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


if __name__ == "__main__":
    unittest.main()
