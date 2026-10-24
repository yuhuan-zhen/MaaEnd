# Linux 侧：从零搭建与理解计划（C++ 版）

面向「用 C++ 调 MaaFramework 原生接口、把 Linux 侧彻底搞懂」的路线。练习册，不是交付清单。

- 基线：`origin/v2` = `a9393386`（2026-10-24）
- 分支：`feat/linux-adapt`
- 参考书：[`docs/`](docs/)（01–05 五篇）
- 产物目录：`tools/linux-adapt/mini-cpp/`
- 仓库约定：推 `yuhuan-zhen/MaaEnd`（fork，SSH 部署密钥）；**不向上游开 PR**

## 合规结论：C++ 是对的语言

| | C++（cpp-algo） | Go（go-service） | C |
| --- | --- | --- | --- |
| MaaEnd agent | ✔ 主力 | ✔ | ✘ 无构建目标 |
| 上游 sample | ✔ | — | 原生接口，能用但无示例 |
| 可被合并 | ✔ | ✔ | ✘ |

所以本计划全程 C++，**规范直接适用**，不需要"语言的妥协"：

- `agent/go-service` 管业务流程，`agent/cpp-algo` 管「单点难算法 + 平台适配」
- `cpp-algo-style` 的命名/头文件/错误处理/CMake 规范全部照做
- 日志用 `<MaaUtils/Logger.h>` 的 `LogInfo << VAR(x)`
- JSON 用 `meojson`
- 图像用 `<MaaUtils/NoWarningCV.hpp>` 引入的 OpenCV

**落位**：学习期放 `tools/linux-adapt/mini-cpp/`（独立 target，不污染 agent 构建）；若将来要合并，搬进 `agent/cpp-algo/source/cloud-webview-linux/`，与 #6800 的 `cloud-webview/` 并列。

## 现成的轮子（不要重写）

`agent/cpp-algo/source/utils.h` 已经提供了本节课要用的全部 RAII 封装：

| 工具 | 用途 |
| --- | --- |
| `ScopedImageBuffer` | `MaaImageBuffer` 的 RAII 包装，禁拷贝 |
| `ScopedStringBuffer` / `ScopedStringListBuffer` | 同上，字符串缓冲 |
| `to_mat(const MaaImageBuffer*)` | 直接转 `cv::Mat`（零拷贝视图） |
| `get_exe_dir()` / `get_install_dir()` / `setup_dll_directory()` | 路径与 DLL 目录 |

**L1 就用 `to_mat`**，不要自己从 `GetRawData` 拼 CV_8UC3。

## 规范对照（照 `cpp-algo-style` 执行）

| 元素 | 规则 | 示例 |
| --- | --- | --- |
| 类 / 结构体 / 枚举 | PascalCase | `MiniController`, `FrameStats` |
| 成员函数 | camelCase | `connect()`, `grabFrame()` |
| 自由函数 | 对外 PascalCase，内部工具 snake_case | `CreateMiniController()`, `write_png()` |
| 成员变量 | snake_case + 尾下划线 | `frame_count_`, `socket_path_` |
| 局部变量 | snake_case | `frame_mat`, `elapsed_ms` |
| 常量 | `k` 前缀 + PascalCase | `kDefaultTimeoutMs` |
| 宏 | ALL_CAPS | `MAA_TRUE` |
| 命名空间 | lowercase | `minicontroller` |
| 头文件 | `#pragma once`，include 顺序：对应头 → 标准库 → 第三方 → `<MaaFramework/...>` `<MaaUtils/...>` → 本项目 `""` | — |
| 日志 | `LogInfo << VAR(x)`，不手拼字符串 | — |
| 错误处理 | 失败必打 `LogError`，不吞错 | — |
| OpenCV | 必须经 `<MaaUtils/NoWarningCV.hpp>` | 禁止 `<opencv2/opencv.hpp>` |

## 六层阶梯

| 层 | 你亲手做什么 | 关键 API / 工具 | 行数 | 我会问什么 |
| --- | --- | --- | --- | --- |
| **L0 环境与最小程序** | 初始化 `MaaUtils` 子模块、拿到 MaaFramework SDK、CMake 链接成功、打印版本并连上 sway | `utils.h`、`MaaVersion`、`MaaLinuxControllerCreate` | ~120 | 为什么所有 handle 都要 RAII？谁释放、什么时候释放？ |
| **L1 截图** | 抓一帧 → `to_mat` → 存 PNG → 打印尺寸/通道/耗时 | `ScopedImageBuffer`、`to_mat`、`cv::imwrite` | ~70 | `to_mat` 是拷贝还是视图？生命周期怎么保证？ |
| **L2 Tasker + Resource** | 加载资源、跑一个 `DirectHit + Click` 节点到 `Succeeded` | `ScopedTasker`/`MaaTaskerCreate`、`MaaResourcePostPath`、`MaaTaskerPostTask` | ~110 | Tasker 为什么必须同时绑 Resource 和 Controller？ |
| **L3 CustomController 骨架** | 实现 21 个回调里的最小集，让框架用**你写的**控制器跑通 L2 那个节点 | `MaaCustomControllerCreate` + 静态函数指针表 | ~180 | `get_features()` 与实现不一致会怎样？ |
| **L4 输入原语** | 补 `swipe` / `click_key` / `scroll` / `relative_move` | 同一回调结构体 | ~170 | `relative_move` 你怎么保证不静默失败？ |
| **L5 任务闭环** | 用自己的控制器跑一次环境监测（进拍照模式 → 扫描） | 纯 pipeline 调用 | ~70 | 为什么 `__CameraScanMove*` 在普通游玩会变成攻击？ |
| **L6 对照上游** | 读 `MaaLinuxControlUnit` 源码，列「我 vs 它」差异表 | 只读 | — | 让你修相对移动，改哪一行？ |

约 720 行 C++。每层可独立停下。

## L3 的回调表（C++ 侧写法）

C API 是纯 C 的，C++ 里用**静态函数 + `void* trans_arg` 转发到自己的对象**：

```cpp
namespace minicontroller
{

struct MiniController
{
    MaaBool connect();
    MaaBool screencap(MaaImageBuffer* out);
    // ...
    std::string socket_path_;
    int frame_count_ = 0;
};

// 回调桥：把 void* 转回对象
MaaBool MAA_CALL ConnectBridge(void* trans_arg);
MaaBool MAA_CALL ScreencapBridge(void* trans_arg, MaaImageBuffer* buffer);
// ...

MaaCustomControllerCallbacks* MakeCallbacks();

} // namespace minicontroller
```

21 个回调的完整签名见 [PLAN.md 的历史版](docs/历史-工程计划-20261024.md) 或 `include/MaaFramework/Instance/MaaCustomController.h`。

**L3 最容易答错的一点**：`get_features()` 返回 `UseMouseDownAndUpInsteadOfClick` 时，框架会**不再调用你的 `click()`**，改成调 `touch_down` + `touch_up`。声明了却不实现后两者，点击就全废。

## L0 的三个前置（这是最容易被卡住的地方）

| 前置 | 难点 | 解法 |
| --- | --- | --- |
| `agent/cpp-algo/MaaUtils` 子模块 | 当前是空目录（未 init），而 `Logger.h`、`NoWarningCV.hpp` 都在里面 | `git -c http.proxy=http://127.0.0.1:7890 submodule update --init agent/cpp-algo/MaaUtils` |
| MaaFramework SDK（头文件 + `.so`） | 不在系统里 | 从 release 包取，或从本机 `maafw` Python 包里挖 `.so`，头文件从仓库取 |
| CMake 目标 | 要能独立编译，不能依赖 cpp-algo 的完整构建 | 独立 `CMakeLists.txt`，`target_link_libraries` 只链 MaaFwCore |

本机直连 github.com 不通，所有 `git submodule` / 下载都要带代理。

## 分工与验收

| 谁 | 做什么 |
| --- | --- |
| 我 | 给骨架与卡点提示、指出错误、验收、答「为什么」 |
| 你 | 敲代码、编译、运行、讲清每层 |

**两道关**：能跑（输出对）+ 能讲（答得出上表提问）。讲不清就回上一层，不硬推。每层在 `mini-cpp/NOTES.md` 写 3–5 行，用自己的话。

## 时间表

| 周 | 内容 |
| --- | --- |
| 第 1 周 | L0 + L1（子模块、链接、第一帧） |
| 第 2 周 | L2（Tasker + Resource + 第一个节点） |
| 第 3 周 | L3 + L4（自己的控制器 + 五种原语） |
| 第 4 周 | L5 + L6（任务闭环 + 差异表） |

## 不在本计划范围内

- 手写 CDP / WebSocket 客户端（需要页面级相对输入时，走 L3 的 `relative_move` 回调 + 上游 `CloudRelativeMove` 契约，见 [04](docs/04-云网页节点契约.md)）
- 向上游提 PR
- 改 `agent/cpp-algo` 现有代码（学习期只在 `tools/linux-adapt/mini-cpp/` 里写新文件）
