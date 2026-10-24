# Linux 适配（自底向上）

面向云终末地网页端（Chrome 串流）在 Linux 上的控制器适配。逐层搭建，每层单独验收后才进入下一层。

- 基线：`origin/v2` = `a9393386`（2026-10-24）
- 分支：`feat/linux-adapt`
- 单次改动上限：2000 行

## 层级

| 层 | 内容 | 状态 |
| --- | --- | --- |
| L1 帧源 | `WlrScreencap` 帧正确性 / 通道序 / 耗时 | ✅ 已验收（8/8） |
| L2 输入原语 | 点击、拖动、键盘、滚轮、相对移动的页面级可见性 | 待开始 |
| L3 节点契约 | `resource_linux` 四个私有节点的实现形式 | 待开始 |
| L4 Go 动作 | `rotateView` / `RelativeMoveAction` 是否需平台分支 | 待开始 |
| L5 任务 | 滑索、环境监测端到端 | 待开始 |
| L6 客户端 | MXU 可视化与暂停、自带入口 | 待开始 |

## L1 结果（2026-10-24）

环境：WSL Ubuntu-24.04，nested sway `wayland-1` 1280×720，MaaFramework v5.14.3。

| 项 | 实测 | 判定 |
| --- | --- | --- |
| connect | 216.2 ms | ✅ |
| 帧 shape | `(720, 1280, 3)` uint8 | ✅ |
| 通道序 | BGR；转 RGB 后与 grim 的 NCC = **1.0**，按 RGB 直接用则 0.757 | ✅ 必须转换 |
| 截图耗时 | min 4.1 / median **16.2** / p95 18.4 / max 18.4 ms | ✅ ≈62 fps |
| 静止画面稳定性 | 20 帧均值标准差 **0.0** | ✅ |
| 与 grim 一致性 | NCC **1.0**（同 zwlr-screencopy 协议，逐像素一致） | ✅ |

对比上一代 CDP 控制器（`Page.captureScreenshot`）：**103–154 ms/帧 → 16 ms/帧**，约 6–9 倍。

### 发现：`MaaControllerGetResolution` 在 Linux 控制器上返回 `(0, 0)`

`resolution` 为 `[0, 0]`，但帧本身是 1280×720。同一实现里 `start_app` 也是 `TODO`，属于 Linux 控制器的 API 未补全部分。

当前影响：无。pipeline 坐标与帧尺寸 1:1（未设置 `display_*` 缩放），ROI 直接落在原始像素上。
潜在影响：任何依赖 `resolution` 做换算的 Client 或脚本会得到 0。L2 若涉及坐标换算需先绕过。

## 运行

```bash
# 直连 github 不通，需走本机代理
git -c http.proxy=http://127.0.0.1:7890 fetch origin v2

# L1 验收（只读截图，不注入输入）
cd tools/linux-adapt
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 python3 l1_screencap.py --n 20
```

产物在 `evidence-l1/`（已 gitignore）：`l1.json`、`frame-bgr2rgb.png`、`ref-grim.png`。
