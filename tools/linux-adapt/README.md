# Linux 适配工作目录

用 C++ 从零搭建 Linux 控制器、并理解 MaaFramework 控制链路的工作区。

## 目录

| 路径 | 内容 | 状态 |
| --- | --- | --- |
| [`PLAN.md`](PLAN.md) | 六层学习计划（L0–L6），C++ 路线 | **现行** |
| [`docs/`](docs/) | 参考书：控制器能力、Wlroots 链路、排障、云网页契约、实测数据 | **现行** |
| `mini-cpp/` | 六层的自建代码（尚未开始） | 待建 |
| [`archive/`](archive/) | 旧 Python 验证线，冻结不再修改 | 归档 |

## 为什么分两半

这条线一开始走「Python binding + `MaaLinuxController` 验证 Wlr 链路」，跑出了 L1 的实测数据
（16.2 ms/帧、NCC 1.0、通道序 BGR）。后来方向改成「C++ 调原生接口、自己实现控制器」，
与 `agent/cpp-algo` 对齐。

旧线不再改动，只保留**能复现实测数据的那一个脚本**，其余教材类内容已删（C++ 版会重写）。

## 现行主线怎么走

看 [`PLAN.md`](PLAN.md)：L0 环境 → L1 截图 → L2 任务 → L3 自己的控制器 → L4 五种输入 → L5 任务闭环 → L6 对照上游。

## 文档与代码的边界

| 只读参考 | 要写的代码 |
| --- | --- |
| `docs/`（五篇，事实与契约） | `mini-cpp/`（六层自建实现） |
| `archive/l1_screencap.py`（期望值来源） | — |

## 证据

`evidence-l1/` 保留 L1 的原始产物（`l1.json`、`frame-bgr2rgb.png`、`ref-grim.png`），已 gitignore，不进仓库。
