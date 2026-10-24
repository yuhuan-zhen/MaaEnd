# 归档：旧 Python 验证线（已冻结）

这条线用 Python binding + `MaaLinuxController`（Wlr）验证 Linux 控制链路，产出了 L1 的实测数据。
2026-10-25 起主线改为 C++（见上级 [`PLAN.md`](../PLAN.md)），本目录**不再修改**。

## 只保留三样东西

| 文件 | 为什么留 |
| --- | --- |
| `l1_screencap.py` | 产出 `docs/05-实测数据.md` 里那些数字的原始脚本，要复现就得靠它 |
| `harness/common.py` | 上面的脚本依赖的公共工具（NCC、通道均值、PNG 保存） |
| `README-L1验收记录.md` | L1 的判定项设计与当时的结论 |

已删除：`study/`（两份逐行注释版 + 精读讲义，共 917 行）和旧工程计划。
C++ 版会重写同类教材，Python 的注释版没有留存价值。

## 运行方式

```bash
cd tools/linux-adapt
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  python3 archive/l1_screencap.py --n 20
```

依赖：`maafw` 5.14+、`numpy`、`pillow`（在仓库 `pyproject.toml` 的 `images` / `pipeline` 组里）。
产物落在 `tools/linux-adapt/evidence-l1/`。
