# Linux 适配执行计划

面向云终末地网页端（Chrome 串流）在 Linux 上的控制器适配。自底向上逐层搭建，每层单独验收通过后才进入下一层。

- 基线：`origin/v2` = `a9393386`（2026-10-24）
- 分支：`feat/linux-adapt`
- 单次改动上限：**2000 行**
- 产物目录：`tools/linux-adapt/`（验收脚本 + 证据 + 文档）
- 上游参照：MaaEnd **#6746**（Windows 网页版宿主，closed）+ MXU **#395**（配套 Custom Controller）

## 目标与非目标

**目标**

1. 用上游 `MaaLinuxControlUnit`（不改上游）跑通云网页端的完整控制链
2. 把「相对移动失效」这条查清，给出最小代价的绕开或修复
3. 环境监测、滑索等真实任务在 Linux 上可跑
4. 保持 MXU 可视化与随时暂停的能力
5. **能复用 #6746 的资产就复用**，不自造平行实现

**非目标**

- 不向上游提交 PR（补丁只留本地）
- 不引入新的控制器类型（继续用 `Linux-Wlroots`）
- 不改动 `MaaEnd-src` 主工作区的既有未提交改动
- 不移植 WebView2 宿主、命名管道 RPC、Custom Controller（见「复用矩阵」：这三件在 Linux 上没有对应物，或没有必要）

## 与 #6746 的对应关系

#6746 那套 = 「宿主 + RPC + Custom Controller + 页面策略」四件套。我们的路线**不引入新控制器类型**，所以前三件都不需要；真正能跨平台复用的是**页面侧**的两块纯 JS 逻辑，以及若干语义约束。

**一句话**：复用它**对页面的所有改动**，不复用它**对 Windows 的所有封装**。

### 复用矩阵

| #6746 / #395 的资产 | 上游位置 | 处置 | 理由 |
| --- | --- | --- | --- |
| `kInputPolicy`（7 条策略） | `agent/cpp-algo/cloud-webview/input_policy.h` | **逐字复用** | 与输入通道无关，纯页面行为：禁 webgl2、废 `focus`/`requestPointerLock`、`keydown` 补 `mouseenter`、中键防自动滚屏、`movementX` 锚点改写、`__maaCloudStartupErrors` |
| `kPageState`（页面状态机） | 同上 | **逐字复用**（L5） | 一次求值返回 `page`/`account`/`video_ready`/`start_target`/`session_busy_confirm_target`/`document_epoch`，决策留给调用方 |
| `prepare()` 八分支 | 宿主侧 | **复用分支划分**（L5） | `ended` / `startup_error` / `login` / `session_busy` / `landing` / `queue` / `starting` / `stream`，只与官网页面有关，与平台无关 |
| `Emulation.setFocusEmulationEnabled` | 文档 + `CloudBridge` | **复用** | 页面失焦不降级渲染/解码；只读 CDP 会话也能设 |
| 127 px 等分 | `CloudBridge.cpp:372` | **复用为规格**，不作 L3 前置 | 串流 SDK 把 movementX 截成 int8；前提是 `relative_move` 能到页面（L2 先验） |
| `key_identity()`（VK → `key`+`code`） | MXU #395 | **复用为 L2 期望值** | VK 27 → `Escape`，VK 65 → `KeyA`；我们用 `use_win32_vk_code: true`，喂进去的就是 VK |
| `contact == -1` = 悬停不按下 | MXU #395 | **复用为 L2 断言** | 决定 hover 能否表达 |
| `video_frame_policy` 取帧 | 同上 | **已超越，不复用** | L1 已改用 `WlrScreencap`：16 ms/帧 vs CDP 103–154 ms |
| SharedBuffer 帧通道 | `cloud_protocol.h` | 不复用 | WebView2 独有 |
| WebView2 宿主 / `FramelessWindow` | `agent/cpp-algo/cloud-webview` | 不复用 | Linux 无 WebView2；我们用真实合成器 + 真实窗口 |
| 命名管道 RPC | `cloud_protocol.h` | 不复用 | 我们的「传输」是 MaaFramework 内置的 Wlroots 注入，不需要额外进程 |
| Custom Controller | MXU #395 | 不复用 | 非目标：不引入新控制器类型 |
| `Win32-CloudWeb` 控制器条目 | `assets/interface.json` | 不复用 | 同上 |

### 由此产生的两处计划修正

1. **L2 增加第 0 步：把 `kInputPolicy` 注入 kiosk Chrome**（只注入策略、不发输入）。它解决三个已知隐患：页面 `requestPointerLock` 抢真光标、失焦降级解码、webgl2 让 `<video>` 被换成 OffscreenCanvas。
2. **L3 默认方案改为「删 remap」**：#6746 在 Windows 上**没有**把 `__CharacterControllerDeltaSwipeAction` 改成相对移动，用的是 base 的 hover 绝对移动 + 页面级 `movementX` 改写。我们在 Linux 拿不到页面级改写（Wlroots 注入的是真指针），但**绝对移动本身有效**（已实测），所以最小改动是「不遮断 base 的实现」，而不是「换一种失效的实现」。

## 分层

| 层 | 内容 | 动手范围 | 上游对应 | 复用方式 | 验收 | 预算 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| L1 帧源 | 帧正确性、通道序、耗时 | `tools/linux-adapt/` | `video_frame_policy` | 已被 `WlrScreencap` 取代 | 8 项判定 + 2 项记录 | 200 行 | ✅ 8/8 |
| L2 输入原语 | 策略注入 + 五种原语页面级可见性 | `tools/linux-adapt/` | `input_policy.h` / MXU 回调 | 策略逐字复用 | 事件表 + 4 条策略断言 | 300 行 | 待开始 |
| L3 节点契约 | `resource_linux` 四个私有节点的实现形式 | `assets/resource_linux/` | base hover 路径 | 删除 remap（等于上游在 Windows 的选择） | yaw / pitch / zipline 三条路各自成立 | 60 行 | 待开始 |
| L4 Go 动作 | `rotateView` / `RelativeMoveAction` 是否需平台分支 | `agent/go-service/` | 无（上游不需要分支） | 默认**不加分支** | 与 L3 一致 | 40 行 | 待开始 |
| L5 任务 | 环境监测、滑索端到端 | pipeline / 探针 | `kPageState` + `prepare()` | 逐字复用 JS + 分支划分 | 实机跑通 | 100 行 | 待开始 |
| L6 客户端 | MXU 可视化与暂停 | 部署配置 | —— | 无需新控制器类型，MXU 直接选 `Linux-Wlroots` | 可重复启动与停止 | 40 行 | 待开始 |

复用带来的预算变化：L2 +50（策略注入）、L4 −110（默认不加分支）、L6 −60（不自带入口），合计 **−120 行**。

每层结束都更新本目录 `README.md` 的验收记录表，并单独提交。

## L1 结论（已完成）

`WlrScreencap` 输出 `(720, 1280, 3)` uint8，**BGR** 通道序（转 RGB 后与 grim 的 NCC = 1.0），耗时中位 16.2 ms（约 62 fps），静止 20 帧完全一致。

与 #6746 的差异：它从 `<video>` 取 **RGBA**（SharedBuffer），我们取 **BGR**（合成器输出），通道序转换是我们独有的，不要照抄它的 RGBA 路径。

已知缺口：`MaaControllerGetResolution` 在本控制器返回 `(0, 0)`，同文件的 `start_app` 也是 `TODO`。坐标与像素目前 1:1，故无实际影响；L2 若用 resolution 做换算需先绕开。

结构重构（2026-10-24，未重跑）：公共工具抽到 `harness/common.py` 供 L2 复用；`--socket` 改由环境变量推导；`resolution` 与 `start_app` 降为**记录项**（`resolution_api` / `start_app`），尺寸判定只用帧 shape——避免「用 `or` 兜底让缺项恒真」。判定项仍 8 项。

## L2 方案：策略注入 + 输入原语页面级验证

**要回答的问题**：五种原语是否真的到达页面、字段是否正确。核心是相对移动（`relative_move`）——它是唯一已知失效的一条。

### 第 0 步：注入 `kInputPolicy`（复用）

在 kiosk Chrome 上开一个**只读 CDP 会话**（`127.0.0.1:9334`）：

```python
Page.addScriptToEvaluateOnNewDocument(source = kInputPolicy)   # 逐字取自 #6746
Runtime.evaluate(kInputPolicy)                                  # 当前文档立即生效
Emulation.setFocusEmulationEnabled(enabled=True)
```

**边界**：这个会话只注入策略与读取状态，**不派发任何输入事件**（输入仍由 `MaaLinuxController` 走 Wlroots 注入）；两者互不干扰这一点本身也要验一次。

验收四条：

| 断言 | 期望 |
| --- | --- |
| `HTMLCanvasElement.prototype.getContext('webgl2')` | `null` |
| `window.focus` / `Element.prototype.requestPointerLock` | 前者空函数，后者返回 rejected Promise |
| 中键 `mousedown` | 浏览器自动滚屏被抑制，不产生 `scroll` |
| `window.__maaCloudStartupErrors` | 存在且为数组 |

### 第 1 步：原语可见性

1. 在 nested chrome 打开本地探针页 `tools/linux-adapt/harness/input_probe.html`，页面把所有指针/键盘/滚轮事件追加到 `window.__events`，字段**与 #6746 的测试对齐**：`type / clientX / clientY / movementX / movementY / button / buttons / code / deltaY`
2. 用 `MaaLinuxController` 依次下发五种原语（不进入游戏，探针页自身不产生副作用）
3. 用只读 CDP 读 `window.__events`，**不注入任何事件**
4. 输出判定表到 `evidence-l2/`

| 原语 | 下发 | 期望页面事件 |
| --- | --- | --- |
| 点击 | `touch_down(0, 640, 560)` + `touch_up(0)` | `pointerdown/pointerup`，`button=0` |
| 悬停 | `touch_down(-1, …)` | **无** `pointerdown`（对齐 MXU #395 的 `contact == -1` 语义） |
| 拖动 | `touch_down → touch_move ×n → touch_up` | 连续 `pointermove` + 按下态，`buttons` 含位 1 |
| 键盘 | `key_down/key_up`（VK 27 与 65） | `keydown/keyup`，`code=Escape/KeyA` |
| 滚轮 | `scroll(640, 360, 0, -3)` | `wheel`，`deltaY` 符号正确 |
| **相对移动** | `relative_move(200, 0)` | 待定，见下 |

### 相对移动的三分支

| 观测 | 结论 | 对 L3/L4 的影响 |
| --- | --- | --- |
| 页面完全无事件 | 合成器未转发（focus 未建立或光标贴边钳制） | 追加一次绝对复位后重试；成立则 L4 加前置复位即可 |
| `clientX` 变化但 `movementX = 0` | 事件到位、形态不符 | L3 删 remap 走 hover 绝对移动，L4 不加分支 |
| `clientX` 不变 | sway 未移动指针 | 上游实现问题，L3 必须绕开相对移动 |

**判定标准**：第 0 步四条 + 第 1 步前五条若任一失败，先修环境（合成器/权限）再继续；相对移动按上表分支记录结论，不阻塞 L3。

## L3 方案：默认删 remap，回落 base hover

现状（`assets/resource_linux/pipeline/Common/Private/CharacterController/Action.json`）：

```json
"__CharacterControllerDeltaSwipeAction": {
    "action": "Custom",
    "custom_action": "CharacterControllerRelativeMoveAction",
    "custom_action_param": { "dx": 0, "dy": 0 }
}
```

**方案 A（默认，等于上游在 Windows 的选择）**：删除这条 remap，让该节点回落到 base 的 `Swipe + only_hover: true`。

- `rotateView` 已经在写 `begin/end`（`begin = (640+cursorDX, 360+cursorDY)`，累积超 ¼ 屏归零），因此不需要任何 Go 侧配合
- Alt / ClickCenter 三个 `DoNothing` 保持不动：cursor 由 Go 的计数器记账，**不依赖真实光标位置**，所以不需要「复位真光标」
- 验收：`YawDelta 90` 可见转动；`ZiplinePitchReset(dy=-1500)` 能把俯仰拉到上限

**方案 B（实验，仅在 L2 判定「追加绝对复位后相对移动可用」时启用）**：保留 remap，在 L4 给 `PostRelativeMove` 前置一次绝对定位。

- 风险：真实光标会移动，且对每次起始位置敏感
- 不作为默认

## L4 方案：默认不加平台分支

#6746 没有任何平台分支——它在 Windows 上完全依赖 base 的绝对移动 + 页面改写。采用 L3 方案 A 后我们同样不需要改 Go：

- `rotateView` 已有 `begin/end`（给 Swipe 族）与 `custom_action_param{dx,dy}`（给相对族）双写
- 选择哪种实现由资源层决定，不由 Go 决定

只有 L3 走方案 B 时才需要改 `agent/go-service/common/charactercontroller/controller.go`（约 40 行），届时单独提交、可单点 revert。

## L5 方案：复用页面状态机

- 逐字复用 `kPageState`（求值一次返回全部状态）与 `prepare()` 的八分支划分
- 预任务组织方式参照 #6746 的 `LoginCloudWeb` / `LaunchCloudWeb`：登录态检查 → 启动游戏 → 等 video 就绪
- 验收：**环境监测**（进拍照模式 → `CameraScanAction` 绝对拖拽扫描）与**滑索**（俯仰基准 + 上索）端到端各跑一次

## L6 方案：MXU 直接可用

因为**不引入新控制器类型**，`Linux-Wlroots` 本来就在 PI 的控制器闭集里，MXU 可以直接选中并连接 kiosk Chrome，F10/F11 与预览面板都无需改造。工作量只剩：

- kiosk 启动脚本（nested sway 输出 + Chrome 参数 + 窗口尺寸 1280×720）
- MXU 实例的控制器选择与资源加载路径

不再需要「自带入口 GUI」。

## 风险与回滚

- 所有验收脚本只读或只作用于**本地探针页**，不向游戏注入输入
- **策略注入是「只注入策略、不发输入」**：L2 第 0 步必须验证注入后 Wlroots 的绝对点击仍然生效
- 产品代码改动集中在 L3（60 行）/ L5（100 行），各自单独提交，可单点 revert
- 证据文件不进 git（`.gitignore` 已排除 `evidence-*/`）
- 不跑 `pnpm check` / `pnpm test`（按 AGENTS.md，交给 CI 或脚本退出码）

## 环境备忘

### 仓库与推送（个人记录用）

- 工作台：`yuhuan-zhen/MaaEnd`（fork），分支 `feat/linux-adapt`
- 远端分工：`fork` 指向自己的 fork（唯一可推）；`origin` / `upstream` 都指向 `MaaEnd/MaaEnd`，只读
- **不向上游 `MaaEnd/MaaEnd` 开 PR**：这条线只作个人记录与本地实践
- 不扩展 CI：不挂 self-hosted runner；L1/L2/L5 在本机手动跑，判定靠脚本退出码

```bash
# 推自己的 fork（需代理）
git -c http.proxy=http://127.0.0.1:7890 push fork feat/linux-adapt

# 拉上游最新
git -c http.proxy=http://127.0.0.1:7890 fetch origin v2
```

### 上游资产（复用来源）

```bash
# #6746 已 closed、未合并；补丁与源码副本已留档
ls ../cloudweb-linux/_ref/pr6746/src/                       # input_policy.h / video_frame_policy.h / CloudBridge.cpp ...
ls ../cloudweb-linux/_ref/pr6746_src/mxu395_cloud_web_controller.rs
```

`input_policy.h` 的 7 条策略与 30 个 JS 用例（`page_state.test.mjs` 17 / `input_policy.test.mjs` 13）可直接作为 L2 的**规格**。

### 运行验收脚本

```bash
# 仓库口径（默认组 scripts + dev 已含 numpy / pillow / maafw）
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  uv run python tools/linux-adapt/<script>.py

# 本机 WSL 无 uv，用系统 Python 3.12 + 已装的等价版本依赖
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  python3 tools/linux-adapt/<script>.py
```

依赖不新增：`numpy` / `pillow` 来自 `images` 组，`maa` 来自 `pipeline` 组的 PyPI 包 `maafw`。
