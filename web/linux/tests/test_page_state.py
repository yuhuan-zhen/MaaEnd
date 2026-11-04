"""``maaend_web.page.prepare`` 的分支回归（不连浏览器）。

移植自上游 ``web/linux/tests/test_page_state.py``（``feat/web-linux-layer`` @ 470d64432），
用例与断言逐字保留，只改两处 import：``page_state`` → ``maaend_web.page``；``page_js``
仍是顶层文件（与 node 测试共用同一份 JS 字符串，导入方式不变）。

JS 状态判定由 page_state.test.mjs 覆盖；这里只测 Python 侧的「求值 → 分支 → 动作」。
跑法：``python -m unittest tests.test_page_state -v``（在 ``web/linux`` 下）。
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import page_js
from maaend_web import page as page_state


class FakeSess:
    """按脚本返回页面状态；记录点击。"""

    def __init__(self, states):
        self.states = list(states)
        self.clicks = []
        self.calls = []

    def ev(self, expr):
        if expr == page_js.PAGE_STATE_JS:
            st = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return json.dumps(st)
        return None

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "Input.dispatchMouseEvent" and params.get("type") == "mousePressed":
            self.clicks.append((params["x"], params["y"]))
        return {}


def st(page, **kw):
    d = {
        "page": page,
        "account": "unknown",
        "video_ready": False,
        "start_target": None,
        "session_busy_confirm_target": None,
        "document_epoch": 1.0,
        "viewport_width": 1280,
        "viewport_height": 720,
    }
    d.update(kw)
    return d


class PrepareTest(unittest.TestCase):
    def test_landing_clicks_start_then_stream(self):
        sess = FakeSess(
            [
                st("landing", start_target={"x": 640, "y": 360}),
                st("stream", video_ready=True, account="signed_in"),
            ]
        )
        self.assertTrue(page_state.prepare(sess, interval=0.01, timeout=5))
        self.assertEqual(sess.clicks, [(640, 360)])

    def test_ended_returns_false(self):
        sess = FakeSess([st("ended", ended=True)])
        self.assertFalse(page_state.prepare(sess, interval=0.01, timeout=5))

    def test_session_busy_confirms(self):
        sess = FakeSess(
            [
                st("session_busy", session_busy_confirm_target={"x": 10, "y": 20}),
                st("stream", video_ready=True),
            ]
        )
        self.assertTrue(page_state.prepare(sess, interval=0.01, timeout=5))
        self.assertEqual(sess.clicks, [(10, 20)])

    def test_login_announced_once_and_waits(self):
        announced = []
        sess = FakeSess(
            [
                st("login", account="signed_out"),
                st("login", account="signed_out"),
                st("stream", video_ready=True),
            ]
        )
        self.assertTrue(page_state.prepare(sess, interval=0.01, timeout=5, on_login=lambda: announced.append(1)))
        self.assertEqual(len(announced), 1, "登录提示只应该打一次")

    def test_landing_without_target_does_not_click(self):
        sess = FakeSess([st("landing", start_target=None)])
        self.assertFalse(page_state.prepare(sess, interval=0.01, timeout=0.05))
        self.assertEqual(sess.clicks, [])

    def test_state_parse_helpers(self):
        s = page_state.State(
            {
                "page": "stream",
                "video_ready": True,
                "viewport_width": 1280,
                "viewport_height": 720,
                "video_width": 1920,
                "video_height": 1080,
                "start_target": {"x": 1.5, "y": 2.5},
                "device_pixel_ratio": 1.5,
            }
        )
        self.assertEqual(s.viewport, (1280, 720))
        self.assertEqual(s.video_size, (1920, 1080))
        self.assertEqual(s.start_target, (1.5, 2.5))
        self.assertTrue(s.video_ready)


class StartupErrorTest(unittest.TestCase):
    """``startup_error`` 分支：默认软重载，给了回调就交给回调（上游 PR 线只测到分支，这里补上）。"""

    def test_default_reloads_soft(self):
        sess = FakeSess([st("startup_error", startup_resource_failed=True), st("stream", video_ready=True)])
        self.assertTrue(page_state.prepare(sess, interval=0.01, timeout=5))
        self.assertIn("Page.reload", [m for m, _ in sess.calls])

    def test_callback_takes_over(self):
        seen = []
        sess = FakeSess([st("startup_error", startup_resource_failed=True), st("stream", video_ready=True)])
        self.assertTrue(
            page_state.prepare(sess, interval=0.01, timeout=5, on_startup_error=lambda s: seen.append(s.page))
        )
        self.assertEqual(seen[:1], ["startup_error"])
        self.assertNotIn("Page.reload", [m for m, _ in sess.calls])


class EdgeCaseTest(unittest.TestCase):
    """``inspect`` 不抛：ev 抛异常 / 返回垃圾 / 返回 list 都退回 page=unknown。"""

    def test_ev_raises(self):
        class Boom:
            def ev(self, expr):
                raise RuntimeError("ws closed")

        self.assertEqual(page_state.inspect(Boom()).page, "unknown")

    def test_garbage_json(self):
        class Garbage:
            def ev(self, expr):
                return "<html>"

        self.assertEqual(page_state.inspect(Garbage()).page, "unknown")

    def test_non_dict(self):
        class NonDict:
            def ev(self, expr):
                return "[1,2,3]"

        self.assertEqual(page_state.inspect(NonDict()).page, "unknown")

    def test_state_defaults(self):
        s = page_state.State()
        self.assertEqual((s.page, s.account, s.viewport), ("unknown", "unknown", (0, 0)))
        self.assertIsNone(s.start_target)
        self.assertEqual(s.document_epoch, 0.0)


if __name__ == "__main__":
    unittest.main()
