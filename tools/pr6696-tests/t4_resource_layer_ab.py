#!/usr/bin/env python3
"""T4 · resource_linux 覆盖层的破坏性（验证 #6696 的「不加载该层」结论）

#6696 的资源加载顺序里没有 `resource_linux`。理由是那一层把
`__CharacterControllerDeltaSwipeAction` remap 成 `Custom → RelativeMove`，而
`RelativeMove` 在 Linux 上实测画面零变化。本脚本做配对实验：

  组 A：只加载 assets/resource
  组 B：加载 assets/resource + assets/resource_linux

每组重复 N 次，每次跑同一个 entry（默认 CharacterControllerExampleYawDeltaRight，
即 delta=90 → dx=180），比较「动作前 / 动作后」两帧的 NCC。

判读：
  - A 组 NCC 明显下降（画面确实转了）
  - B 组 NCC 接近 1.0（画面没动，动作被 remap 掉）
  - 两组必须在同一场地、同一朝向、连续测量，否则不能直接比

前提：
  1. 需要一个可用的 Wayland 合成器（sway），且 socket 路径可访问
  2. **需要真实游戏画面**——没有游戏时本脚本只能证明「动作被接受且无报错」，
     不能证明「画面转了」
  3. 依赖 maafw（Python binding）：uv run --with maafw python t4_resource_layer_ab.py

用法：
  python3 t4_resource_layer_ab.py --repo ../../MaaEnd-src --socket /run/user/0/wayland-1
  python3 t4_resource_layer_ab.py --mode on --repeat 1     # 只跑 B 组
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

try:
    import numpy as np
    from maa.controller import LinuxController
    from maa.resource import Resource
    from maa.tasker import Tasker
except ImportError:  # pragma: no cover - 环境提示
    raise SystemExit(
        "需要 maafw 与 numpy：uv run --with maafw --with numpy python t4_resource_layer_ab.py"
    ) from None

import _common as c

DEFAULT_ENTRY = "CharacterControllerExampleYawDeltaRight"


def find_repo(explicit: str | None) -> pathlib.Path:
    if explicit:
        repo = pathlib.Path(explicit)
        if not (repo / "assets" / "resource").exists():
            raise SystemExit(f"{repo} 下没有 assets/resource")
        return repo
    here = pathlib.Path(__file__).resolve().parent
    for candidate in (here.parent.parent / "MaaEnd-src", here.parent.parent / "MaaEnd-linux-adapt"):
        if (candidate / "assets" / "resource").exists():
            return candidate
    raise SystemExit("找不到 MaaEnd 仓库，请用 --repo 指定")


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关。1.0 = 完全一致，接近 0 = 无关。"""
    left = a.astype(np.float64).ravel()
    right = b.astype(np.float64).ravel()
    left -= left.mean()
    right -= right.mean()
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(left, right) / denominator)


def grab(controller: LinuxController) -> np.ndarray | None:
    job = controller.post_screencap()
    job.wait()
    image = job.get()
    if image is None:
        return None
    array = np.asarray(image)
    return array[:, :, ::-1] if array.ndim == 3 else array  # BGR → RGB，仅用于一致性


def run_group(mode: str, repo: pathlib.Path, socket_path: str, entry: str, repeat: int) -> list[dict]:
    paths = [str(repo / "assets" / "resource")]
    if mode == "on":
        paths.append(str(repo / "assets" / "resource_linux"))

    controller = LinuxController({
        "screencap_method": 1,
        "input_method": 1,
        "wlr_socket_path": socket_path,
        "use_win32_vk_code": True,
    })
    started = time.time()
    if not controller.post_connection().wait().succeeded:
        raise SystemExit("控制器连接失败：检查 socket 路径与合成器是否在运行")
    connect_ms = round((time.time() - started) * 1000)

    resource = Resource()
    for path in paths:
        resource.post_bundle(path).wait()
    tasker = Tasker()
    tasker.bind(resource, controller)

    rows = []
    for index in range(1, repeat + 1):
        before = grab(controller)
        job = tasker.post_task(entry, "{}")
        job.wait()
        settle = 0.35  # 相机平滑需要一点时间；不是 pipeline 的延迟，是测量需要
        time.sleep(settle)
        after = grab(controller)
        if before is None or after is None:
            rows.append({"mode": mode, "run": index, "ncc": None, "note": "截图失败"})
            continue
        value = ncc(before, after)
        shape = f"{after.shape[1]}x{after.shape[0]}"
        rows.append({"mode": mode, "run": index, "ncc": round(value, 4), "note": shape})
    return [{"connect_ms": connect_ms, "layers": [p.split("/")[-1] for p in paths]}] + rows


def main() -> int:
    parser = argparse.ArgumentParser(description="T4 resource_linux 覆盖层配对实验")
    parser.add_argument("--repo", help="MaaEnd 仓库根（含 assets/resource）")
    parser.add_argument("--socket", default="/run/user/0/wayland-1", help="Wayland socket")
    parser.add_argument("--entry", default=DEFAULT_ENTRY, help="要跑的 pipeline entry")
    parser.add_argument("--repeat", type=int, default=3, help="每组重复次数（默认 3）")
    parser.add_argument("--mode", choices=["off", "on", "both"], default="both",
                        help="off=不加载 resource_linux；on=加载；both=先后都跑")
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    repo = find_repo(args.repo)
    evidence = c.Evidence("t4", pathlib.Path(args.out))
    print(f"仓库：{repo}")
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")

    modes = ["off", "on"] if args.mode == "both" else [args.mode]
    all_rows: dict[str, list[dict]] = {}
    for mode in modes:
        label = "加载 resource_linux" if mode == "on" else "不加载 resource_linux"
        print(f"\n== {label} ==")
        rows = run_group(mode, repo, args.socket, args.entry, args.repeat)
        all_rows[mode] = rows
        for row in rows:
            print(f"  {row}")

    print("\n汇总（NCC：1.0 = 画面完全没变，越低说明确实转了）")
    table = []
    for mode, rows in all_rows.items():
        values = [row["ncc"] for row in rows if isinstance(row.get("ncc"), float)]
        if values:
            stats = c.summarize(values)
            table.append(["resource_linux" if mode == "on" else "base",
                          f"{stats['median']:.4f}", f"{stats['min']:.4f}",
                          f"{stats['max']:.4f}", stats["n"]])
    c.print_table(table, ["资源层", "median NCC", "min", "max", "n"])

    print("\n判读：")
    print("  - base 组 NCC 明显低于 1（如 0.2-0.5）→ 画面转了，动作有效")
    print("  - resource_linux 组 NCC 接近 1.0 → 动作被 remap 掉，画面没动")
    print("  - 若两组都接近 1.0，先确认是否真的在游戏画面里（停在官网/加载页会得到同样结果）")
    evidence.write_json("summary.json", all_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
