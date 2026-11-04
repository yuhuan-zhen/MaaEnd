"""``maaend_web.jsonc`` 的离线回归：注释、尾逗号、BOM、报错路径。

不需要 maa、不连网：全部是纯字符串/临时文件操作。

跑法：``python -m unittest discover -s web/linux/tests -v``（在仓库根）。
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from maaend_web.jsonc import load_jsonc, loads_jsonc


class StrictJsonTest(unittest.TestCase):
    """标准 JSON 先走快速通道，不能被清理规则改坏。"""

    def test_plain_object(self) -> None:
        self.assertEqual(loads_jsonc('{"a": 1, "b": [true, null]}'), {"a": 1, "b": [True, None]})

    def test_url_inside_string_is_untouched(self) -> None:
        # 字符串里的 // 不是注释；这里能直接过标准 JSON，所以走快速通道。
        self.assertEqual(loads_jsonc('{"u": "https://web.hycdn.cn/x.js"}'), {"u": "https://web.hycdn.cn/x.js"})

    def test_bom_is_stripped(self) -> None:
        self.assertEqual(loads_jsonc('\ufeff{"a": 1}'), {"a": 1})

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            loads_jsonc('{"a": }')


class CommentTest(unittest.TestCase):
    """发行版的 interface.json / bundle 里这四种注释都会出现。"""

    def test_line_comment_on_own_line(self) -> None:
        text = '{\n  // 整行注释\n  "a": 1\n}'
        self.assertEqual(loads_jsonc(text), {"a": 1})

    def test_trailing_line_comment(self) -> None:
        text = '{\n  "a": 1, // 行尾注释\n  "b": 2\n}'
        self.assertEqual(loads_jsonc(text), {"a": 1, "b": 2})

    def test_block_comment(self) -> None:
        text = '{/* 块注释\n跨行 */ "a": 1}'
        self.assertEqual(loads_jsonc(text), {"a": 1})

    def test_url_then_trailing_comment(self) -> None:
        # 同一个对象里既有含 // 的字符串、又有真注释：快速通道失败，清理规则不能切坏 URL。
        text = '{\n  "u": "https://web.hycdn.cn/x.js", // CDN\n  "n": 1\n}'
        self.assertEqual(loads_jsonc(text), {"u": "https://web.hycdn.cn/x.js", "n": 1})

    def test_i18n_skip_marker(self) -> None:
        # pipeline 里的 // @i18n-skip 是行注释，必须能被吃掉。
        text = '{\n  "expected": [\n    // "稳定生产 100%"\n    // @i18n-skip\n    "稳定生产"\n  ]\n}'
        self.assertEqual(loads_jsonc(text), {"expected": ["稳定生产"]})


class TrailingCommaTest(unittest.TestCase):
    def test_object_trailing_comma(self) -> None:
        self.assertEqual(loads_jsonc('{"a": 1,}'), {"a": 1})

    def test_array_trailing_comma(self) -> None:
        self.assertEqual(loads_jsonc('{"a": [1, 2,]}'), {"a": [1, 2]})

    def test_nested_trailing_commas(self) -> None:
        self.assertEqual(loads_jsonc('{"a": {"b": [1,],},}'), {"a": {"b": [1]}})


class LoadFileTest(unittest.TestCase):
    """``load_jsonc``：文件层，BOM 与编码按 utf-8-sig 吃。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reads_bom_and_comments(self) -> None:
        p = self.root / "interface.json"
        p.write_text('\ufeff{\n  // 注释\n  "version": "v1",\n}\n', encoding="utf-8")
        self.assertEqual(load_jsonc(p), {"version": "v1"})

    def test_accepts_str_path(self) -> None:
        p = self.root / "a.json"
        p.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(load_jsonc(str(p)), {"a": 1})

    def test_missing_file_raises_oserror(self) -> None:
        with self.assertRaises(OSError):
            load_jsonc(self.root / "nope.json")


if __name__ == "__main__":
    unittest.main()
