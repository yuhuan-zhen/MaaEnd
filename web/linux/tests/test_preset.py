"""preset 的离线回归：三层选项展开、input 占位符类型转换、缺失/未知 case、预设装载。

跑法：python -m unittest discover -s web/linux/tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maaend_web.preset import (
    MAX_DEPTH,
    PlanItem,
    case_names_of,
    deep_merge,
    load_all,
    load_interface,
    load_preset,
    resolve_task,
)


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def task_of(*options: str, name: str = "DemoTask") -> dict:
    return {"name": name, "entry": "DemoEntry", "option": list(options)}


class DeepMergeTest(unittest.TestCase):
    def test_recursive_merge(self) -> None:
        dst = {"NodeA": {"a": 1, "b": 1}, "NodeB": {"x": 1}}
        deep_merge(dst, {"NodeA": {"b": 2, "c": 3}})
        self.assertEqual(dst, {"NodeA": {"a": 1, "b": 2, "c": 3}, "NodeB": {"x": 1}})

    def test_list_replaced_not_merged(self) -> None:
        dst = {"NodeA": {"attach": ["a", "b"]}}
        deep_merge(dst, {"NodeA": {"attach": ["c"]}})
        self.assertEqual(dst, {"NodeA": {"attach": ["c"]}})

    def test_returns_dst(self) -> None:
        dst: dict = {}
        self.assertIs(deep_merge(dst, {"k": 1}), dst)


class CaseNamesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.options = {
            "Sw": {"type": "switch", "cases": [{"name": "Yes"}, {"name": "No"}]},
            "Cb": {"type": "checkbox", "cases": [{"name": "A"}, {"name": "B"}]},
            "Sel": {"type": "select", "cases": [{"name": "A"}, {"name": "B"}]},
            "Inp": {"type": "input", "cases": [{"name": "A"}]},
        }

    def test_switch_defaults_to_yes(self) -> None:
        self.assertEqual(case_names_of("Sw", {}, self.options), ["Yes"])

    def test_switch_honours_default_case(self) -> None:
        options = {"Sw": {"type": "switch", "cases": [{"name": "Yes"}, {"name": "No"}], "default_case": "No"}}
        self.assertEqual(case_names_of("Sw", {}, options), ["No"])

    def test_switch_false_means_no(self) -> None:
        self.assertEqual(case_names_of("Sw", {"value": False}, self.options), ["No"])

    def test_checkbox_drops_unknown_names(self) -> None:
        self.assertEqual(case_names_of("Cb", {"caseNames": ["B", "Zz"]}, self.options), ["B"])

    def test_select_unknown_case_returns_empty(self) -> None:
        self.assertEqual(case_names_of("Sel", {"caseName": "Zz"}, self.options), [])

    def test_input_falls_back_to_first_case(self) -> None:
        self.assertEqual(case_names_of("Inp", {}, self.options), ["A"])


class ResolveTaskTest(unittest.TestCase):
    def test_checkbox_expands_three_levels(self) -> None:
        """第三层必须真的合并：2026-10-20 的 28 条 attach 就是丢在这一层。"""
        options = {
            "Outer": {
                "type": "checkbox",
                "cases": [
                    {"name": "A", "pipeline_override": {"Node1": {"a": 1}}, "option": ["Mid"]},
                    {"name": "B", "pipeline_override": {"Node1": {"b": 2}}},
                ],
            },
            "Mid": {
                "type": "checkbox",
                "cases": [{"name": "C", "pipeline_override": {"Node2": {"c": 3}}, "option": ["Inner"]}],
            },
            "Inner": {
                "type": "checkbox",
                "cases": [{"name": "D", "pipeline_override": {"Node3": {"d": 4}}}],
            },
        }
        values = {
            "Outer": {"caseNames": ["A"]},
            "Mid": {"caseNames": ["C"]},
            "Inner": {"caseNames": ["D"]},
        }
        override, notes = resolve_task(task_of("Outer"), options, values)
        self.assertEqual(override, {"Node1": {"a": 1}, "Node2": {"c": 3}, "Node3": {"d": 4}})
        self.assertEqual(notes, ["Outer=A", "Mid=C", "Inner=D"])

    def test_checkbox_default_case_used_when_unset(self) -> None:
        options = {
            "Cb": {
                "type": "checkbox",
                "default_case": ["A"],
                "cases": [{"name": "A", "pipeline_override": {"N": {"v": 1}}}, {"name": "B"}],
            }
        }
        override, notes = resolve_task(task_of("Cb"), options, {})
        self.assertEqual(override, {"N": {"v": 1}})
        self.assertEqual(notes, ["Cb=A"])

    def test_checkbox_unknown_case_is_noted_and_skipped(self) -> None:
        options = {"Cb": {"type": "checkbox", "cases": [{"name": "A", "pipeline_override": {"N": {"v": 1}}}]}}
        override, notes = resolve_task(task_of("Cb"), options, {"Cb": {"caseNames": ["A", "Zz"]}})
        self.assertEqual(override, {"N": {"v": 1}})
        self.assertIn("UNKNOWN_CASE:Cb.Zz", notes)

    def test_select_unknown_case_is_noted(self) -> None:
        options = {"Sel": {"type": "select", "cases": [{"name": "A", "pipeline_override": {"N": {"v": 1}}}]}}
        override, notes = resolve_task(task_of("Sel"), options, {"Sel": {"caseName": "Nope"}})
        self.assertEqual(override, {})
        self.assertIn("UNKNOWN_CASE:Sel=Nope", notes)

    def test_select_uses_case(self) -> None:
        options = {
            "Sel": {
                "type": "select",
                "cases": [{"name": "A", "pipeline_override": {"N": {"v": 1}}}, {"name": "B", "pipeline_override": {"N": {"v": 2}}}],
            }
        }
        override, notes = resolve_task(task_of("Sel"), options, {"Sel": {"caseName": "B"}})
        self.assertEqual(override, {"N": {"v": 2}})
        self.assertEqual(notes, ["Sel=B"])

    def test_switch_yes_and_no(self) -> None:
        options = {
            "Sw": {
                "type": "switch",
                "cases": [
                    {"name": "Yes", "pipeline_override": {"N": {"on": True}}},
                    {"name": "No", "pipeline_override": {"N": {"on": False}}},
                ],
            }
        }
        self.assertEqual(resolve_task(task_of("Sw"), options, {"Sw": {"value": False}})[0], {"N": {"on": False}})
        self.assertEqual(resolve_task(task_of("Sw"), options, {})[0], {"N": {"on": True}})

    def test_input_full_placeholder_becomes_int(self) -> None:
        options = {
            "Inv": {
                "type": "input",
                "inputs": [{"name": "MaxCount", "default": "5", "pipeline_type": "int"}],
                "pipeline_override": {"NodeA": {"max_count": "{MaxCount}"}},
            }
        }
        override, _notes = resolve_task(task_of("Inv"), options, {})
        self.assertEqual(override, {"NodeA": {"max_count": 5}})
        self.assertIsInstance(override["NodeA"]["max_count"], int)

    def test_input_full_placeholder_becomes_bool(self) -> None:
        options = {
            "Inv": {
                "type": "input",
                "inputs": [{"name": "Enabled", "default": "true", "pipeline_type": "bool"}],
                "pipeline_override": {"NodeA": {"enabled": "{Enabled}"}},
            }
        }
        override, _notes = resolve_task(task_of("Inv"), options, {})
        self.assertIs(override["NodeA"]["enabled"], True)

    def test_input_embedded_placeholder_stays_string(self) -> None:
        options = {
            "Inv": {
                "type": "input",
                "inputs": [
                    {"name": "MaxCount", "default": "5", "pipeline_type": "int"},
                    {"name": "Tag", "default": "abc"},
                ],
                "pipeline_override": {"NodeA": {"label": "{Tag}-{MaxCount}"}},
            }
        }
        override, _notes = resolve_task(task_of("Inv"), options, {})
        self.assertEqual(override, {"NodeA": {"label": "abc-5"}})
        self.assertIsInstance(override["NodeA"]["label"], str)

    def test_input_values_from_option_values(self) -> None:
        options = {
            "Inv": {
                "type": "input",
                "inputs": [{"name": "MaxCount", "default": "5", "pipeline_type": "int"}],
                "pipeline_override": {"NodeA": {"max_count": "{MaxCount}"}},
            }
        }
        override, _notes = resolve_task(task_of("Inv"), options, {"Inv": {"values": {"MaxCount": "42"}}})
        self.assertEqual(override, {"NodeA": {"max_count": 42}})

    def test_input_empty_value_falls_back_to_default(self) -> None:
        options = {
            "Inv": {
                "type": "input",
                "inputs": [{"name": "MaxCount", "default": "9", "pipeline_type": "int"}],
                "pipeline_override": {"NodeA": {"max_count": "{MaxCount}"}},
            }
        }
        override, _notes = resolve_task(task_of("Inv"), options, {"Inv": {"values": {"MaxCount": ""}}})
        self.assertEqual(override, {"NodeA": {"max_count": 9}})

    def test_input_missing_value_skips_whole_override(self) -> None:
        options = {
            "Inv": {
                "type": "input",
                "inputs": [{"name": "Need"}],
                "pipeline_override": {"NodeA": {"v": "{Need}", "keep": 1}},
            }
        }
        override, notes = resolve_task(task_of("Inv"), options, {})
        self.assertEqual(override, {})
        self.assertIn("MISSING_INPUT:Inv.Need", notes)

    def test_input_runtime_placeholder_is_preserved(self) -> None:
        """未声明为 input 的 {X} 是运行时变量，必须原样保留。"""
        options = {
            "Inv": {
                "type": "input",
                "inputs": [{"name": "MaxCount", "default": "5", "pipeline_type": "int"}],
                "pipeline_override": {"NodeA": {"v": "{AutoStockCurrentStockBill}", "n": "{MaxCount}"}},
            }
        }
        override, notes = resolve_task(task_of("Inv"), options, {})
        self.assertEqual(override, {"NodeA": {"v": "{AutoStockCurrentStockBill}", "n": 5}})
        self.assertFalse([n for n in notes if n.startswith("MISSING_INPUT")])

    def test_task_pipeline_override_lands_first(self) -> None:
        task = {
            "name": "DemoTask",
            "entry": "DemoEntry",
            "pipeline_override": {"NodeA": {"a": 1, "b": 1}},
            "option": ["Sw"],
        }
        options = {
            "Sw": {
                "type": "switch",
                "cases": [
                    {"name": "Yes", "pipeline_override": {"NodeA": {"b": 2, "c": 3}}},
                    {"name": "No", "pipeline_override": {"NodeA": {"a": 9}}},
                ],
            }
        }
        override, _notes = resolve_task(task, options, {"Sw": {"value": True}})
        self.assertEqual(override, {"NodeA": {"a": 1, "b": 2, "c": 3}})

    def test_value_placeholder(self) -> None:
        options = {"Sel": {"type": "select", "cases": [{"name": "A", "pipeline_override": {"N": {"text": "$value"}}}]}}
        override, _notes = resolve_task(task_of("Sel"), options, {"Sel": {"caseName": "A", "value": "hello"}})
        self.assertEqual(override, {"N": {"text": "hello"}})

    def test_deep_option_tree_truncates(self) -> None:
        options = {}
        for i in range(MAX_DEPTH + 3):
            options[f"O{i}"] = {
                "type": "checkbox",
                "default_case": ["Yes"],
                "cases": [
                    {
                        "name": "Yes",
                        "pipeline_override": {f"N{i}": {"v": i}},
                        "option": [f"O{i + 1}"],
                    }
                ],
            }
        override, notes = resolve_task(task_of("O0"), options, {})
        self.assertIn(f"TRUNCATED:O{MAX_DEPTH + 1}", notes)
        self.assertEqual(len(override), MAX_DEPTH + 1)

    def test_option_cycle_does_not_recurse(self) -> None:
        options = {
            "Loop": {
                "type": "checkbox",
                "default_case": ["Yes"],
                "cases": [{"name": "Yes", "pipeline_override": {"N": {"v": 1}}, "option": ["Loop"]}],
            }
        }
        override, notes = resolve_task(task_of("Loop"), options, {})
        self.assertEqual(override, {"N": {"v": 1}})
        self.assertEqual(notes, ["Loop=Yes"])

    def test_unknown_option_key_is_noted_not_raised(self) -> None:
        override, notes = resolve_task(task_of("Nope"), {}, {"Nope": {"caseNames": ["A"]}})
        self.assertEqual(override, {})
        self.assertEqual(notes, ["Nope=?"])


class LoadInterfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "maaend"
        self.root.mkdir()
        write_json(
            self.root / "interface.json",
            {"import": ["tasks/*.json", "tasks/broken/*.json", str(self.root / "abs.json")]},
        )
        write_json(
            self.root / "tasks" / "a.json",
            {
                "task": [{"name": "Alpha", "entry": "AlphaEntry"}],
                "option": {"Grp": {"type": "switch", "cases": [{"name": "Yes"}, {"name": "No"}]}},
            },
        )
        write_json(
            self.root / "tasks" / "b.json",
            {"tasks": [{"name": "Beta", "entry": "BetaEntry"}, {"entry": "NoName"}, "not-a-dict"]},
        )
        write_json(self.root / "abs.json", {"task": [{"name": "Gamma", "entry": "GammaEntry"}]})
        (self.root / "tasks" / "c.json").write_text('{"task": [ this is not json ]}', encoding="utf-8")

    def test_tasks_and_options_are_collected(self) -> None:
        tasks, options = load_interface(self.root)
        self.assertEqual(sorted(tasks), ["Alpha", "Beta", "Gamma"])
        self.assertEqual(tasks["Alpha"]["entry"], "AlphaEntry")
        self.assertIn("Grp", options)

    def test_broken_file_is_skipped(self) -> None:
        tasks, _options = load_interface(self.root)
        self.assertNotIn("c", tasks)

    def test_load_all_is_the_old_alias(self) -> None:
        self.assertIs(load_all, load_interface)


class LoadPresetTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "maaend"
        self.root.mkdir()
        write_json(self.root / "interface.json", {"import": ["tasks/*.json"]})
        write_json(
            self.root / "tasks" / "tasks.json",
            {
                "task": [
                    {"name": "VisitFriends", "entry": "VisitFriendsEntry", "option": ["Who"]},
                    {"name": "WebOpenMenu", "entry": "WebPressEscEntry"},
                ],
                "option": {
                    "Who": {
                        "type": "checkbox",
                        "cases": [{"name": "A", "pipeline_override": {"N": {"v": 1}}}],
                    }
                },
            },
        )
        write_json(
            self.root / "config" / "mxu-MaaEnd.json",
            {
                "instances": [
                    {
                        "id": "friend-a",
                        "name": "朋友家",
                        "controllerName": "Linux-Wlroots",
                        "resourceName": "官服-网页端",
                        "tasks": [
                            {"taskName": "VisitFriends", "enabled": True, "optionValues": {"Who": {"caseNames": ["A"]}}},
                            {"taskName": "WebOpenMenu", "enabled": False},
                            {"taskName": "NotInInterface"},
                            {"taskName": "WebStartGame"},
                            {"taskName": "VisitFriends", "optionValues": "boom"},
                        ],
                    }
                ]
            },
        )

    def test_instance_found_by_id(self) -> None:
        inst, plan = load_preset("friend-a", root=self.root)
        self.assertEqual(inst["name"], "朋友家")
        self.assertEqual(len(plan), 5)

    def test_instance_found_by_name(self) -> None:
        inst, _plan = load_preset("朋友家", root=self.root)
        self.assertEqual(inst["id"], "friend-a")

    def test_missing_instance_raises_lookup_error(self) -> None:
        with self.assertRaises(LookupError) as ctx:
            load_preset("nope", root=self.root)
        self.assertEqual(str(ctx.exception), "找不到实例: nope")

    def test_plan_item_fields(self) -> None:
        _inst, plan = load_preset("friend-a", root=self.root)
        first = plan[0]
        self.assertEqual(first.name, "VisitFriends")
        self.assertEqual(first.entry, "VisitFriendsEntry")
        self.assertTrue(first.enabled)
        self.assertEqual(first.override, {"N": {"v": 1}})
        self.assertEqual(first.notes, ["Who=A"])
        self.assertEqual(first.n_override, 1)
        self.assertIsNone(first.error)

    def test_disabled_task_kept_with_flag(self) -> None:
        _inst, plan = load_preset("friend-a", root=self.root)
        self.assertFalse(plan[1].enabled)

    def test_missing_task_becomes_error_item(self) -> None:
        _inst, plan = load_preset("friend-a", root=self.root)
        self.assertIsNone(plan[2].entry)
        self.assertEqual(plan[2].error, "任务不存在于接口")
        self.assertEqual(plan[2].n_override, 0)

    def test_fallback_entry_for_web_tasks(self) -> None:
        _inst, plan = load_preset("friend-a", root=self.root)
        self.assertEqual(plan[3].entry, "WebStartGameEntry")
        self.assertEqual(plan[3].notes, ["内置回退"])

    def test_task_level_exception_is_captured(self) -> None:
        _inst, plan = load_preset("friend-a", root=self.root)
        self.assertEqual(plan[4].entry, "VisitFriendsEntry")
        self.assertTrue(plan[4].notes[0].startswith("ERROR:"))
        self.assertEqual(plan[4].override, {})

    def test_dict_style_access(self) -> None:
        _inst, plan = load_preset("friend-a", root=self.root)
        item = plan[0]
        self.assertEqual(item["name"], "VisitFriends")
        self.assertEqual(item["n_override"], 1)
        self.assertEqual(item.get("override"), {"N": {"v": 1}})
        self.assertEqual(item.get("n_override", -1), 1)
        self.assertIsNone(item.get("missing"))
        self.assertEqual(item.get("missing", "dflt"), "dflt")
        with self.assertRaises(KeyError):
            _ = item["missing"]

    def test_config_path_implies_root(self) -> None:
        inst, plan = load_preset("friend-a", config_path=self.root / "config" / "mxu-MaaEnd.json")
        self.assertEqual(inst["id"], "friend-a")
        self.assertEqual(len(plan), 5)

    def test_plan_item_is_a_dataclass_too(self) -> None:
        item = PlanItem(name="X", entry="XEntry")
        self.assertEqual(item.override, {})
        self.assertEqual(item.notes, [])
        self.assertEqual(item.n_override, 0)


if __name__ == "__main__":
    unittest.main()
