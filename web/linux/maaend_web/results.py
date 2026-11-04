"""跑批结果的 JSONL 落盘与汇总文本。

字段顺序就是 JSONL 里的键顺序，与重构前 ``record()`` 写出的对象一致：name、entry、done、succeeded、seconds、last_node、timeout、attempt。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class TaskResult:
    """单个任务的最终结果。"""

    name: str
    entry: str
    done: bool
    succeeded: bool
    seconds: float
    last_node: str | None
    timeout: bool
    attempt: int


class ResultWriter:
    """把结果追加进 JSONL，并生成与重构前逐字一致的汇总。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, result: TaskResult) -> None:
        """追加一行 JSONL；父目录不存在时先建出来（旧 record() 的 makedirs 行为）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

    def summary(self, results: Sequence[TaskResult]) -> str:
        """生成汇总文本：标题行 + 每项一行（OK/TIMEOUT/FAIL）+ 通过计数，逐行与旧日志相同。"""
        lines = ["==== 汇总 ===="]
        for r in results:
            flag = "OK  " if r.succeeded else ("TIMEOUT" if r.timeout else "FAIL")
            lines.append(f"  {r.name:<22} {flag:<8} {r.seconds:6.1f}s  {r.last_node or ''}")
        ok = sum(1 for r in results if r.succeeded)
        lines.append(f"通过 {ok} / {len(results)}")
        return "\n".join(lines)
