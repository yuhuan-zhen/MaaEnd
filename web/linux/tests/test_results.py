"""``maaend_web.results`` 的离线回归：JSONL 键顺序、追加语义、汇总文本。

汇总文本是 ``--dry-run``/生产日志的对拍对象之一，格式改动必须走这里。

跑法：``python -m unittest discover -s web/linux/tests -v``（在仓库根）。
"""

import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from maaend_web.results import ResultWriter, TaskResult

FIELDS = ["name", "entry", "done", "succeeded", "seconds", "last_node", "timeout", "attempt"]


def make(name="WebStartGame", ok=True, timeout=False, seconds=12.34, last_node=None, attempt=1) -> TaskResult:
    return TaskResult(
        name=name,
        entry="WebStartGameEntry",
        done=not timeout,
        succeeded=ok,
        seconds=seconds,
        last_node=last_node,
        timeout=timeout,
        attempt=attempt,
    )


class TaskResultTest(unittest.TestCase):
    def test_field_order_is_the_jsonl_contract(self) -> None:
        # 历史 jsonl 读取方按位置/键名读，顺序不能变。
        self.assertEqual(list(asdict(make())), FIELDS)

    def test_defaults_are_plain_builtins(self) -> None:
        d = asdict(make())
        self.assertIsInstance(d["seconds"], float)
        self.assertIsInstance(d["attempt"], int)
        self.assertIsNone(d["last_node"])


class ResultWriterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_creates_parent_dir_and_writes_one_line(self) -> None:
        path = self.root / "nested" / "daily_linux_progress.jsonl"
        ResultWriter(path).write(make())
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(list(json.loads(lines[0])), FIELDS)

    def test_appends_instead_of_truncating(self) -> None:
        path = self.root / "progress.jsonl"
        writer = ResultWriter(path)
        writer.write(make(name="A"))
        writer.write(make(name="B"))
        names = [json.loads(line)["name"] for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(names, ["A", "B"])

    def test_writes_utf8_without_escaping(self) -> None:
        path = self.root / "progress.jsonl"
        ResultWriter(path).write(make(name="采集"))
        self.assertIn("采集", path.read_text(encoding="utf-8"))

    def test_accepts_str_path(self) -> None:
        path = self.root / "progress.jsonl"
        ResultWriter(str(path)).write(make())
        self.assertTrue(path.is_file())


class SummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.writer = ResultWriter(Path(self.tmp.name) / "unused.jsonl")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_flags_and_counts(self) -> None:
        text = self.writer.summary(
            [
                make(name="A", ok=True, seconds=1.0),
                make(name="B", ok=False, timeout=False, seconds=2.0),
                make(name="C", ok=False, timeout=True, seconds=3.0),
            ]
        ).splitlines()
        self.assertEqual(text[0], "==== 汇总 ====")
        self.assertIn("OK", text[1])
        self.assertIn("FAIL", text[2])
        self.assertIn("TIMEOUT", text[3])
        self.assertEqual(text[-1], "通过 1 / 3")

    def test_line_shape_is_fixed_width(self) -> None:
        line = self.writer.summary([make(name="A", ok=True, seconds=1.0)]).splitlines()[1]
        # "  <name:22><flag:8><seconds:6.1f>s  <last_node>"
        self.assertTrue(line.startswith("  A "))
        self.assertIn("  1.0s", line)

    def test_last_node_rendered_when_present(self) -> None:
        line = self.writer.summary([make(name="A", ok=True, last_node="WebAlreadyInGame")]).splitlines()[1]
        self.assertTrue(line.endswith("WebAlreadyInGame"))

    def test_empty_results(self) -> None:
        self.assertEqual(self.writer.summary([]), "==== 汇总 ====\n通过 0 / 0")


if __name__ == "__main__":
    unittest.main()
