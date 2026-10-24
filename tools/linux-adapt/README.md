# Linux 适配工作目录

用 C++ 从零搭建 Linux 控制器、并理解 MaaFramework 控制链路的工作区。

## 目录

| 路径 | 内容 | 状态 |
| --- | --- | --- |
| [`PLAN.md`](PLAN.md) | 六层学习计划（L0–L6），C++ 路线 | **现行** |
| [`docs/`](docs/) | 参考书：控制器能力、Wlroots 链路、排障、云网页契约、实测数据 | **现行** |
| `mini-cpp/` | 六层的自建代码（尚未开始） | 待建 |
| [`archive/`](archive/) | 旧 Python 验证线，冻结不再修改 | 归档 |

## 为什么分成两半

这条线一开始走的是「用 Python binding + `MaaLinuxController` 验证 Wlr 链路」，跑出了 L1 的实测数据（16.2 ms、NCC 1.0、BGR）。
后来方向改成「用 C++ 调原生接口、自己实现控制器」，与 `agent/cpp-algo` 对齐。

旧线不再改动，但**不要删**——它提供两样新线仍然需要的东西：

1. **期望值**：C++ 版 L1 要复现同样的帧尺寸、通道序与耗时量级
2. **教材**：`archive/study/` 里对旧脚本的逐行注释，讲的是 BGR、NCC、视口这些与语言无关的概念

## 现行主线怎么走

看 [`PLAN.md`](PLAN.md)。一句话：L0 环境 → L1 截图 → L2 任务 → L3 自己的控制器 → L4 五种输入 → L5 任务闭环 → L6 对照上游。

## 归档目录怎么跑

```bash
# 旧脚本仍可运行（路径已变，命令里的目录要改）
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  python3 tools/linux-adapt/archive/l1_screencap.py --n 20
```

产物仍在 `../evidence-l1/`（相对脚本位置变成 `archive/../evidence-l1/`，即 `tools/linux-adapt/evidence-l1/`）。

## 证据

`evidence-l1/` 保留 L1 的原始产物（`l1.json`、`frame-bgr2rgb.png`、`ref-grim.png`），已 gitignore，不进仓库。
