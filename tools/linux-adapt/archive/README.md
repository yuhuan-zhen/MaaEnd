# 归档：旧 Python 验证线（已冻结）

这条线用 Python binding + `MaaLinuxController`（Wlr）验证 Linux 控制链路，产出了 L1 的实测数据。
2026-10-25 起主线改为 C++（见上级 [`PLAN.md`](../PLAN.md)），本目录**不再修改**，只作为参照物保留。

## 保留它有什么用

| 价值 | 说明 |
| --- | --- |
| **期望值** | C++ 版 L1 要复现同样的结果：帧 1280×720、通道序 BGR、耗时 16 ms 量级、与 `grim` 对比 NCC = 1.0 |
| **教材** | `study/` 里对旧脚本的逐行注释，讲的是 BGR / NCC / 视口 / uint8 溢出这些与语言无关的概念 |
| **证据** | `L1验收记录.md` 里有完整的实测数字与当时的判定项设计 |

## 内容

| 文件 | 内容 |
| --- | --- |
| `l1_screencap.py` | L1 脚本：连控制器 → 抓 20 帧 → 与 grim 对照 → 输出判定 |
| `harness/common.py` | 公共工具（NCC、通道均值、PNG 保存） |
| `study/` | 逐行注释版（`*_annotated.py`）与精读讲义（`README.md`） |
| `README-L1验收记录.md` | L1 的验收记录与判据设计 |
| `历史-工程计划-20261024.md` | 旧的六层工程计划（Python 路线，后被 C++ 路线取代） |

## 为什么冻结而不是删除

- 删掉就丢了「期望值」的原始出处（`docs/05-实测数据.md` 的数字来自这里）
- `study/` 那两篇注释版是花了功夫的教材，C++ 版会另写，但概念部分是通用的
- 冻结成本为零：不进构建、不被引用、不影响主线

## 运行方式

```bash
cd tools/linux-adapt
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  python3 archive/l1_screencap.py --n 20
```

依赖：`maafw` 5.14+、`numpy`、`pillow`（均在本仓库 `pyproject.toml` 的 `images` / `pipeline` 组里）。

产物落在 `tools/linux-adapt/evidence-l1/`（相对脚本位置是 `archive/../evidence-l1/`）。
