"""按 ``--tasks`` / ``--only`` / ``--from-to`` 从计划里挑出本次要跑的任务。

三条选择语义与重构前的 ``run_daily_linux.py`` 逐字一致：先过滤掉没有 entry 或被预设禁用的项，再按 1 基序号定位。
"""

from __future__ import annotations

from collections.abc import Sequence

from .preset import PlanItem


def _runnable(plan: Sequence[PlanItem]) -> list[PlanItem]:
    """只留能跑的项：有 entry 且没被预设禁用。"""
    return [p for p in plan if p.entry and p.enabled]


def select_plan(
    plan: Sequence[PlanItem],
    *,
    tasks: str = "",
    only: str = "",
    frm: int = 1,
    to: int = 99,
) -> list[PlanItem]:
    """按 ``--tasks`` / ``--only`` / ``--from-to`` 选出本次要跑的项。

    优先级与旧 CLI 一致：``tasks`` 给了就只认 ``tasks``，否则看 ``only``，都没给才用 ``frm``/``to``。
    """
    return select_plan_with_notes(plan, tasks=tasks, only=only, frm=frm, to=to)[0]


def select_plan_with_notes(
    plan: Sequence[PlanItem],
    *,
    tasks: str = "",
    only: str = "",
    frm: int = 1,
    to: int = 99,
) -> tuple[list[PlanItem], list[str]]:
    """同 :func:`select_plan`，但把「序号越界 / 未知任务」这类提示一并返回，由 CLI 加前缀打印。

    提示文案刻意保持旧日志的原文（``序号越界: %s`` / ``未知任务: %s``），这样 ``--dry-run`` 的输出与重构前一致。
    """
    runnable = _runnable(plan)
    notes: list[str] = []
    if tasks:
        tokens = [t.strip() for t in tasks.replace("，", ",").split(",") if t.strip()]
        picked: list[PlanItem] = []
        for tok in tokens:
            if tok.isdigit():
                i = int(tok)
                if 1 <= i <= len(runnable):
                    picked.append(runnable[i - 1])
                else:
                    notes.append(f"序号越界: {tok}")
            elif "-" in tok and all(x.strip().isdigit() for x in tok.split("-")):
                lo, hi = [int(x) for x in tok.split("-")]
                picked += runnable[max(0, lo - 1) : hi]
            else:
                hit = [p for p in runnable if p.name.lower() == tok.lower()]
                if hit:
                    picked.append(hit[0])
                else:
                    notes.append(f"未知任务: {tok}")
        return picked, notes
    if only:
        want = {int(x) for x in only.split(",") if x.strip()}
        return [p for i, p in enumerate(runnable, 1) if i in want], notes
    return [p for i, p in enumerate(runnable, 1) if frm <= i <= to], notes
