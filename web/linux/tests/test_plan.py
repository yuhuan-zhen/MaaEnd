"""plan 的离线回归：过滤、序号/名字/区间选择、--only 与 --from/--to 的优先级。

跑法：python -m unittest discover -s web/linux/tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maaend_web.plan import select_plan, select_plan_with_notes
from maaend_web.preset import PlanItem


def sample_plan() -> list[PlanItem]:
    return [
        PlanItem(name="WebStartGame", entry="WebStartGameEntry"),
        PlanItem(name="AutoCollect", entry="AutoCollectEntry"),
        PlanItem(name="DeliveryJobs", entry="DeliveryJobsEntry"),
        PlanItem(name="SellProduct", entry="SellProductEntry"),
        PlanItem(name="ProtocolSpace", entry="ProtocolSpaceEntry"),
        PlanItem(name="VisitFriends", entry="VisitFriendsEntry"),
        PlanItem(name="DijiangRewards", entry="DijiangRewardsEntry"),
        PlanItem(name="Disabled", entry="DisabledEntry", enabled=False),
        PlanItem(name="NoEntry", entry=None),
    ]


def names(items: list[PlanItem]) -> list[str]:
    return [p.name for p in items]


class FilterTest(unittest.TestCase):
    def test_disabled_and_entryless_are_dropped(self) -> None:
        self.assertEqual(
            names(select_plan(sample_plan())),
            [
                "WebStartGame",
                "AutoCollect",
                "DeliveryJobs",
                "SellProduct",
                "ProtocolSpace",
                "VisitFriends",
                "DijiangRewards",
            ],
        )

    def test_empty_plan(self) -> None:
        self.assertEqual(select_plan([]), [])

    def test_disabled_item_not_reachable_by_name(self) -> None:
        picked, notes = select_plan_with_notes(sample_plan(), tasks="Disabled")
        self.assertEqual(picked, [])
        self.assertEqual(notes, ["未知任务: Disabled"])

    def test_entryless_item_not_reachable_by_index(self) -> None:
        picked, notes = select_plan_with_notes(sample_plan(), tasks="9")
        self.assertEqual(picked, [])
        self.assertEqual(notes, ["序号越界: 9"])


class TasksTest(unittest.TestCase):
    def test_range_1_to_5(self) -> None:
        picked = select_plan(sample_plan(), tasks="1-5")
        self.assertEqual(
            names(picked),
            ["WebStartGame", "AutoCollect", "DeliveryJobs", "SellProduct", "ProtocolSpace"],
        )

    def test_names_list(self) -> None:
        picked = select_plan(sample_plan(), tasks="WebStartGame,VisitFriends")
        self.assertEqual(names(picked), ["WebStartGame", "VisitFriends"])

    def test_full_width_comma(self) -> None:
        picked = select_plan(sample_plan(), tasks="WebStartGame，VisitFriends")
        self.assertEqual(names(picked), ["WebStartGame", "VisitFriends"])

    def test_name_is_case_insensitive(self) -> None:
        self.assertEqual(names(select_plan(sample_plan(), tasks="webstartgame")), ["WebStartGame"])

    def test_single_index(self) -> None:
        self.assertEqual(names(select_plan(sample_plan(), tasks="3")), ["DeliveryJobs"])

    def test_indices_and_range_mix(self) -> None:
        picked = select_plan(sample_plan(), tasks="1,3-4")
        self.assertEqual(names(picked), ["WebStartGame", "DeliveryJobs", "SellProduct"])

    def test_range_beyond_end_is_clipped(self) -> None:
        picked = select_plan(sample_plan(), tasks="6-99")
        self.assertEqual(names(picked), ["VisitFriends", "DijiangRewards"])

    def test_duplicates_are_kept(self) -> None:
        """旧 CLI 不去重，重复序号就是跑两次；这里保持同样的行为。"""
        self.assertEqual(names(select_plan(sample_plan(), tasks="1,1")), ["WebStartGame", "WebStartGame"])

    def test_out_of_range_index_is_noted(self) -> None:
        picked, notes = select_plan_with_notes(sample_plan(), tasks="1,99")
        self.assertEqual(names(picked), ["WebStartGame"])
        self.assertEqual(notes, ["序号越界: 99"])

    def test_unknown_name_is_noted(self) -> None:
        picked, notes = select_plan_with_notes(sample_plan(), tasks="Nope")
        self.assertEqual(picked, [])
        self.assertEqual(notes, ["未知任务: Nope"])

    def test_blank_tokens_ignored(self) -> None:
        self.assertEqual(names(select_plan(sample_plan(), tasks=" , 2 , ")), ["AutoCollect"])


class OnlyTest(unittest.TestCase):
    def test_only_uses_one_based_indices(self) -> None:
        self.assertEqual(names(select_plan(sample_plan(), only="1,3")), ["WebStartGame", "DeliveryJobs"])

    def test_only_ignores_out_of_range(self) -> None:
        self.assertEqual(names(select_plan(sample_plan(), only="99")), [])

    def test_tasks_wins_over_only(self) -> None:
        picked = select_plan(sample_plan(), tasks="VisitFriends", only="1")
        self.assertEqual(names(picked), ["VisitFriends"])


class FromToTest(unittest.TestCase):
    def test_from_to_slice(self) -> None:
        self.assertEqual(names(select_plan(sample_plan(), frm=2, to=4)), ["AutoCollect", "DeliveryJobs", "SellProduct"])

    def test_default_range_covers_all(self) -> None:
        self.assertEqual(len(select_plan(sample_plan())), 7)

    def test_reversed_range_is_empty(self) -> None:
        self.assertEqual(select_plan(sample_plan(), frm=5, to=2), [])


class ImmutabilityTest(unittest.TestCase):
    def test_input_plan_is_not_modified(self) -> None:
        plan = sample_plan()
        before = [(p.name, p.entry, p.enabled, list(p.notes)) for p in plan]
        select_plan(plan, tasks="1-3")
        after = [(p.name, p.entry, p.enabled, list(p.notes)) for p in plan]
        self.assertEqual(before, after)
        self.assertEqual(len(plan), 9)

    def test_selection_returns_original_items(self) -> None:
        plan = sample_plan()
        picked = select_plan(plan, tasks="VisitFriends")
        self.assertIs(picked[0], plan[5])


if __name__ == "__main__":
    unittest.main()
