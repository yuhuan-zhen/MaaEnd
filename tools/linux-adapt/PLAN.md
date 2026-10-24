# Linux 侧：从零搭建与理解计划（C++ 版）

面向「用 C++ 调 MaaFramework 原生接口、把 Linux 侧彻底搞懂」的路线。练习册，不是交付清单。

- 基线：`origin/v2` = `a9393386`（2026-10-24）
- 分支：`feat/linux-adapt`
- 本仓库参考书：[`docs/`](docs/)（01–05 五篇）
- 产物目录：`tools/linux-adapt/mini-cpp/`
- 仓库约定：推 `yuhuan-zhen/MaaEnd`（fork，SSH 部署密钥）；**不向上游开 PR**

## 这一轮重审改了什么

| # | 问题 | 修正 |
| --- | --- | --- |
| 1 | 每层没有文档锚点，遇到问题只能靠猜 | 新增「上游文档索引」+ 每层挂短码（`[FW-2.2]` 等） |
| 2 | L1/L2 用框架自带控制器，L3 换成自己的，读者不知道代码会被替换 | 明确写清：**L1/L2 的控制器代码在 L3 会被替换，这是刻意的**——先证明环境通，再替换实现 |
| 3 | L5 依赖真游戏，卡住就没退路 | 给出退路：用 `DbgController` 喂静态图跑 pipeline，验证「节点链路通」而非「游戏成功」 |
| 4 | 只写了「能跑」，没写每层最常见卡点 | 每层补「卡点」与「验收判据」 |

## 合规结论：C++ 是对的语言

| | C++（cpp-algo） | Go（go-service） | C |
| --- | --- | --- | --- |
| MaaEnd agent | ✔ 主力 | ✔ | ✘ 无构建目标 |
| 上游 sample | ✔ | — | 能用但无示例 |
| 可被合并 | ✔ | ✔ | ✘ |

规范直接适用，无需语言妥协：`cpp-algo-style`（命名/头文件/错误处理/CMake）、`maa-logging`（`LogInfo << VAR(x)`）、`meojson`（JSON）、`<MaaUtils/NoWarningCV.hpp>`（OpenCV）。

**落位**：学习期 `tools/linux-adapt/mini-cpp/`（独立 target）；将来若合并，搬进 `agent/cpp-algo/source/cloud-webview-linux/`，与 #6800 的 `cloud-webview/` 并列。

## 上游文档索引

短码在下面各层表格里引用。

| 短码 | 文档 | 用在哪层 |
| --- | --- | --- |
| `[FW-1.1]` | [快速开始](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.1-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md) | L0 环境 |
| `[FW-1.2]` | [术语解释](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.2-%E6%9C%AF%E8%AF%AD%E8%A7%A3%E9%87%8A.md) | 全程（本体/资源/agent/Tasker） |
| `[FW-1.3]` | [Custom & Agent](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.3-Custom%26Agent.md) | L3（跨进程 vs 同进程） |
| `[FW-2.1]` | [集成文档](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.1-%E9%9B%86%E6%88%90%E6%96%87%E6%A1%A3.md) | 选语言、看 binding 支持矩阵 |
| `[FW-2.2]` | [集成接口一览](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.2-%E9%9B%86%E6%88%90%E6%8E%A5%E5%8F%A3%E4%B8%80%E8%A7%88.md) | L0–L4（每个 create / post / wait 的签名） |
| `[FW-2.3]` | [回调协议](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.3-%E5%9B%9E%E8%B0%83%E5%8D%8F%E8%AE%AE.md) | L2（任务状态）、L3（controller 回调） |
| `[FW-2.4]` | [控制方式说明](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.4-%E6%8E%A7%E5%88%B6%E6%96%B9%E5%BC%8F%E8%AF%B4%E6%98%8E.md) | L1、L4（Wlr/PipeWire/UInput/Libei 全表） |
| `[FW-3.1]` | [任务流水线协议](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md) | L2、L5（节点字段） |
| `[FW-3.3]` | [ProjectInterface V2](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.3-ProjectInterfaceV2%E5%8D%8F%E8%AE%AE.md) | L5（控制器闭集、display_*） |
| `[FW-4.1]` | [构建指南](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/4.1-%E6%9E%84%E5%BB%BA%E6%8C%87%E5%8D%97.md) | L0（自己编 SDK 时的选项） |
| `[FW-4.2]` | [标准化接口设计](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/4.2-%E6%A0%87%E5%87%86%E5%8C%96%E6%8E%A5%E5%8F%A3%E8%AE%BE%E8%AE%A1.md) | L3（为什么 C 接口是 handle + 回调表） |
| `[HDR]` | [MaaCustomController.h](https://github.com/MaaXYZ/MaaFramework/blob/main/include/MaaFramework/Instance/MaaCustomController.h) · [MaaController.h](https://github.com/MaaXYZ/MaaFramework/blob/main/include/MaaFramework/Instance/MaaController.h) · [MaaBuffer.h](https://github.com/MaaXYZ/MaaFramework/blob/main/include/MaaFramework/Utility/MaaBuffer.h) | L0–L4 的权威签名 |
| `[SRC-LINUX]` | [source/MaaLinuxControlUnit](https://github.com/MaaXYZ/MaaFramework/tree/main/source/MaaLinuxControlUnit) | L6 对照 |
| `[SRC-LOOP]` | [ControllerAgent.cpp](https://github.com/MaaXYZ/MaaFramework/blob/main/source/MaaFramework/Controller/ControllerAgent.cpp) | L3 理解框架怎么调你的回调 |
| `[ME-1]` | [MaaEnd getting-started](https://github.com/MaaEnd/MaaEnd/blob/v2/docs/zh_cn/developers/getting-started.md) | L0（工具链、uv、构建） |
| `[ME-2]` | [coding-standards](https://github.com/MaaEnd/MaaEnd/blob/v2/docs/zh_cn/developers/coding-standards.md) | 全程（提交前检查清单） |
| `[ME-3]` | [components/character-controller](https://github.com/MaaEnd/MaaEnd/blob/v2/docs/zh_cn/developers/components/character-controller.md) | L5（转视角节点语义） |
| `[ME-4]` | 仓库内 `.agents/skills/cpp-algo-style`、`maa-logging`、`pipeline-guide` | 全程 |

## 现成的轮子（不要重写）

`agent/cpp-algo/source/utils.h`：

| 工具 | 用途 | 用在哪层 |
| --- | --- | --- |
| `ScopedImageBuffer` | `MaaImageBuffer` RAII，禁拷贝 | L1 |
| `ScopedStringBuffer` / `ScopedStringListBuffer` | 同上 | L3（`request_uuid` / `get_info`） |
| `to_mat(const MaaImageBuffer*)` | 转 `cv::Mat`（**视图，非拷贝**） | L1 |
| `get_exe_dir()` / `get_install_dir()` | 路径 | L2（资源路径） |

## 六层阶梯

### L0 环境与最小程序（~120 行）

| 项 | 内容 |
| --- | --- |
| 做什么 | 初始化 `MaaUtils` 子模块、拿到 SDK、独立 CMake 链接成功、`MaaVersion()` 打出版本、`MaaLinuxControllerCreate` 连上 sway |
| 参考 | `[FW-1.1]` `[FW-2.2]` `[HDR]` `[ME-1]` |
| 卡点 | ① `MaaUtils` 是空子模块（`Logger.h`/`NoWarningCV.hpp` 在里面）② `.so` 名字不确定 ③ 运行期找不到库（rpath） |
| 验收 | 打印出版本号；`MaaControllerPostConnection` 返回成功 |

### L1 截图（~70 行）

| 项 | 内容 |
| --- | --- |
| 做什么 | 抓一帧 → `to_mat` → `cv::imwrite` 存 PNG → 打印尺寸/通道/耗时 |
| 参考 | `[FW-2.4]`（Linux Screencap）`[HDR]`（`MaaImageBufferGetRawData/Type`）`[FW-2.2]`（`post_screencap`） |
| 卡点 | **`to_mat` 是视图**：`ScopedImageBuffer` 析构后再用 `cv::Mat` 就是悬空指针，务必 `imwrite` 在作用域内完成 |
| 验收 | PNG 能打开、1280×720、通道数 3；耗时与 `docs/05` 的 16.2 ms 同量级 |

### L2 Tasker + Resource（~110 行）

| 项 | 内容 |
| --- | --- |
| 做什么 | 加载资源、绑 Resource 与 Controller、跑一个 `DirectHit + Click` 节点到 `Succeeded` |
| 参考 | `[FW-2.2]`（`MaaTaskerCreate` / `MaaResourcePostPath` / `MaaTaskerPostTask`）`[FW-3.1]`（节点字段）`[FW-2.3]`（任务状态回调） |
| 卡点 | ① 资源路径要指向**包含 `pipeline`/`image`/`model` 的目录**，指到 `pipeline` 子目录会加载不到模板 ② Tasker 未绑 Controller 就跑任务会失败 |
| 验收 | 任务 `succeeded`，日志里能看到节点被执行 |

### L3 CustomController 骨架（~180 行）

| 项 | 内容 |
| --- | --- |
| 做什么 | 实现 21 个回调里的最小集，让框架用**你写的**控制器跑通 L2 那个节点 |
| 参考 | `[HDR]`（`MaaCustomControllerCallbacks` 全字段）`[FW-1.3]`（同进程 vs 跨进程）`[FW-4.2]`（为什么是 handle + 回调表）`[SRC-LOOP]` |
| 卡点 | ① 回调表是**裸函数指针**，其生命周期必须长于 controller ② `get_features()` 声明了 `UseMouseDownAndUpInsteadOfClick` 却没实现 `touch_down/up`，点击全废 ③ `void* trans_arg` 要能转回自己的对象 |
| 验收 | 同一个 pipeline 节点，用你自己的控制器也 `succeeded`；L1/L2 的控制器代码在此被替换（**刻意设计**：先证明环境通，再替换实现） |

### L4 输入原语（~170 行）

| 项 | 内容 |
| --- | --- |
| 做什么 | 补 `swipe` / `click_key` / `scroll` / `relative_move` |
| 参考 | `[FW-2.4]`（Wlr/UInput/Libei 的输入方式差异）`[ME-3]`（转视角节点语义）本仓库 [`docs/02`](docs/02-Wlroots输入链路解剖.md) |
| 卡点 | ① `contact` 在鼠标型输入下是左/右/中键，不是手指号 ② 相对移动在 Wlroots 链路上无效且**不报错**——自己的实现要显式打日志 ③ 键码空间（VK vs evdev） |
| 验收 | 探针页收到四种事件；`relative_move` 若无效果，日志必须能说清"发了但无效" |

### L5 任务闭环（~70 行）

| 项 | 内容 |
| --- | --- |
| 做什么 | 用自己的控制器跑一次环境监测（进拍照模式 → 扫描） |
| 参考 | `[ME-3]` `[FW-3.1]` `[FW-3.3]` 本仓库 [`docs/04`](docs/04-云网页节点契约.md) |
| 卡点 | ① `__CameraScanMove*` 是**带按键的拖拽**，只能在拍照模式用，普通游玩会变成普通攻击（实测 12 次 = 12 次普攻）② 需要游戏在跑 |
| 退路（无游戏时） | 用 `MaaDbgControllerCreate(read_path)` 喂静态图跑 pipeline，只验证「节点链路通」，不验证「游戏成功」。判据改为：预期的节点序列被执行 |
| 验收 | 有游戏：任务成功；无游戏：节点链路按预期走完 |

### L6 对照上游（只读）

| 项 | 内容 |
| --- | --- |
| 做什么 | 读 `[SRC-LINUX]` 四个文件（`LinuxControlUnitMgr` / `WlrInput` / `WlrScreencap` / `WaylandClient`），列「我 vs 它」差异表 |
| 输出格式 | 表：能力 / 上游实现 / 我的实现 / 差异原因 / 谁更合理 |
| 验收 | 差异表能解释两件事：为什么相对移动失效、上游为什么把截图和输入拆成两个策略对象 |

## L0 的三个前置

| 前置 | 难点 | 解法 |
| --- | --- | --- |
| `agent/cpp-algo/MaaUtils` 子模块 | 当前是**空目录** | `git -c http.proxy=http://127.0.0.1:7890 submodule update --init agent/cpp-algo/MaaUtils` |
| MaaFramework SDK（头 11 个 + `.so`） | 不在系统里 | 三选一：① release 包（含 `include/` 与 `bin/`）② 本机 `maafw` Python 包里的 `.so` + 仓库 `include/` ③ 按 `[FW-4.1]` 自行构建 |
| 独立 CMake 目标 | 不能依赖 cpp-algo 完整构建 | 单独 `CMakeLists.txt`，只链 MaaFwCore；用 `ldd` 确认依赖 |

本机直连 `github.com` 不通，所有 `git submodule` 与下载都要带代理。

## 分工与验收

| 谁 | 做什么 |
| --- | --- |
| 我 | 给骨架与卡点提示、指出错误、验收、答「为什么」 |
| 你 | 敲代码、编译、运行、讲清每层 |

**两道关**：能跑（验收判据达成）+ 能讲（答得出每层隐含的问题）。讲不清就回上一层。每层在 `mini-cpp/NOTES.md` 写 3–5 行，用自己的话。

## 时间表

| 周 | 内容 | 说明 |
| --- | --- | --- |
| 第 1 周 | L0 + L1 | L0 可能占满整周（子模块 + SDK + 链接是最碎的部分） |
| 第 2 周 | L2 | 第一个能跑的任务 |
| 第 3 周 | L3 + L4 | 自己的控制器 + 五种原语 |
| 第 4 周 | L5 + L6 | 任务闭环 + 差异表 |

## 不在本计划范围内

- 手写 CDP / WebSocket 客户端（需要页面级相对输入时走 L3 的 `relative_move` 回调 + 上游 `CloudRelativeMove` 契约，见 [`docs/04`](docs/04-云网页节点契约.md)）
- 向上游提 PR
- 修改 `agent/cpp-algo` 现有代码（学习期只写 `tools/linux-adapt/mini-cpp/` 下的新文件）
