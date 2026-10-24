# Linux 侧：从零搭建与理解计划（C 语言版）

面向「用 C 调 MaaFramework 原生接口、把 Linux 侧彻底搞懂」的路线。练习册，不是交付清单。

- 基线：`origin/v2` = `a9393386`（2026-10-24）
- 分支：`feat/linux-adapt`
- 参考书：[`docs/`](docs/)（01–05 五篇）
- 产物目录：`tools/linux-adapt/mini-c/`
- 仓库约定：推 `yuhuan-zhen/MaaEnd`（fork，SSH 部署密钥）；**不向上游开 PR**

## 先定语言与合规（重要）

| | C 语言 | C++（cpp-algo） | Go（go-service） |
| --- | --- | --- | --- |
| 上游 MaaFramework | **原生接口**，官方支持 | 官方 sample 语言 | 无 |
| MaaEnd agent | **没有 C 构建目标** | ✔ 主力 | ✔ |
| 定位 | 合规的「**集成方式**」 | 合规的「**可合并代码**」 | 同左 |

三句话说清：

1. **C 是 MaaFramework 的一等公民**。`2.1-集成文档` 里 C++ 那一行写着「原生接口 ✔ / 标准化接口 ❌」——纯 C 就是「原生接口」这一档，`MaaAPI.h` 提供全部能力。
2. **MaaEnd 没有 C 代码**。agent 只有 `cpp-algo`（C++）与 `go-service`（Go），构建系统里没有 C 目标，C 代码进不去。
3. 所以 C 的正确落位是**独立宿主/工具程序**（`tools/linux-adapt/mini-c/`），能跑、能演示、能讲清；但不要指望它被 MaaEnd 合并。

若目标改成「能被合并」，就得写 C++ 并对齐 `cpp-algo-style`。那条路与本计划的差别只在语法，架构与六层完全一致。

## 规范映射：C 代码怎么长得像这个项目

仓库的 `cpp-algo-style` / `maa-logging` 是 C++ 规范，可搬到 C 的部分：

| 规范条目（C++） | C 里怎么写 |
| --- | --- |
| 结构体 / 枚举 PascalCase | `struct MiniController`, `enum Phase` |
| 自由函数对外 PascalCase、内部工具 snake_case | `MiniControllerCreate()`, `write_png()` |
| 变量 snake_case、成员尾下划线 | `int frame_count_;` |
| 常量 `k` 前缀 + PascalCase | `kMaxFrames` |
| 宏 ALL_CAPS | `LOG_ERROR(...)` |
| include 顺序 | 对应头 → 标准库 → 第三方 → `<MaaFramework/...>` → 本项目 `""` |
| 不吞错，失败必打日志 | 每个回调 `return MAA_FALSE` 前必须有一条 `LOG_ERROR` |
| 缓冲区 create/destroy 配对 | 用 `goto cleanup` 保证释放（对应 C++ 的 `ScopedImageBuffer`） |

**唯一无法对齐处**：`<MaaUtils/Logger.h>` 的 `LogInfo << VAR(x)` 是 C++ 流式宏，C 用不了。替代为 printf 风格宏：

```c
#define LOG_INFO(...)  log_write("INFO", __VA_ARGS__)
#define LOG_ERROR(...) log_write("ERR ", __VA_ARGS__)
```

属于「语言限制导致的偏离」，文档里注明即不算违规。

## 六层阶梯

| 层 | 你亲手做什么 | 关键 C API | 行数 | 我会问什么 |
| --- | --- | --- | --- | --- |
| **L0 环境与最小程序** | 拿到 `include/` + `.so`，写 CMakeLists，链接成功，打印版本并连上 sway | `MaaVersion`, `MaaLinuxControllerCreate`, `MaaControllerPostConnection` | ~70 | 为什么 C 里 handle 都是不透明指针？谁负责释放？ |
| **L1 截图** | 抓一帧 → 取编码字节 → 写盘 → 确认是 PNG，打印尺寸 | `MaaControllerPostScreencap`, `MaaImageBufferGetEncoded`, `...GetEncodedSize` | ~60 | 取「编码后」比取 raw 省了什么？代价是什么？ |
| **L2 Tasker + Resource** | 加载资源，跑一个 `DirectHit + Click` 节点到 `Succeeded` | `MaaTaskerCreate`, `MaaResourcePostPath`, `MaaTaskerBindResource/BindController`, `MaaTaskerPostTask` | ~90 | 为什么 Tasker 必须同时绑 Resource 和 Controller？ |
| **L3 CustomController 骨架** | 填 21 个回调里的最小集合，让框架用**你写的**控制器跑通 L2 的节点 | `MaaCustomControllerCreate` | ~150 | `get_features()` 为什么必须与实现一致？不一致会怎样？ |
| **L4 输入原语** | 补 `swipe` / `click_key` / `scroll` / `relative_move` | 同一回调结构体 | ~150 | `relative_move` 你怎么保证不静默失败？ |
| **L5 任务闭环** | 用 L3/L4 的控制器跑一次环境监测 | 纯 C 调用 pipeline | ~60 | 为什么 `__CameraScanMove*` 在普通游玩会变成攻击？ |
| **L6 对照上游** | 读 `MaaLinuxControlUnit` 源码，列「我 vs 它」差异表 | 只读 | — | 让你修相对移动，改哪一行？ |

约 580 行 C 代码。每层可独立停下，停在任何一层都有可运行产物。

## 21 个回调（L3 全貌）

```c
MaaBool (*connect)(void*);
MaaBool (*connected)(void*);
MaaBool (*request_uuid)(void*, MaaStringBuffer*);
MaaControllerFeature (*get_features)(void*);
MaaBool (*start_app)(const char*, void*);
MaaBool (*stop_app)(const char*, void*);
MaaBool (*screencap)(void*, MaaImageBuffer*);
MaaBool (*click)(int32_t, int32_t, void*);
MaaBool (*swipe)(int32_t, int32_t, int32_t, int32_t, int32_t, void*);
MaaBool (*touch_down)(int32_t, int32_t, int32_t, int32_t, void*);
MaaBool (*touch_move)(int32_t, int32_t, int32_t, int32_t, void*);
MaaBool (*touch_up)(int32_t, void*);
MaaBool (*click_key)(int32_t, void*);
MaaBool (*input_text)(const char*, void*);
MaaBool (*key_down)(int32_t, void*);
MaaBool (*key_up)(int32_t, void*);
MaaBool (*scroll)(int32_t, int32_t, void*);
MaaBool (*relative_move)(int32_t, int32_t, void*);
MaaBool (*shell)(const char*, int64_t, void*, MaaStringBuffer*);
MaaBool (*inactive)(void*);
MaaBool (*get_info)(void*, MaaStringBuffer*);
```

L3 只填必需项，其余留 `NULL`（框架会走默认行为）。**`get_features()` 决定框架是否把你的 `click` 改写成 `touch_down/up`** —— 这是 L3 最容易答错的一点。

## 构建前置（L0 的第一件事）

头文件与动态库不在系统里，需要：

1. 取 `include/MaaFramework/*`（11 个头文件）
2. 取 `libMaaFwCore.so`（版本与 binding 对齐，当前 5.14.3）

L0 第一步就是**确认库的真实文件名与依赖**：

```bash
ls /usr/local/lib/python3.12/dist-packages/maa/*.so 2>/dev/null
ldd <那个 .so> | grep -i maa
```

拿到名字再写最小 `CMakeLists.txt`，先只调 `MaaVersion()` 验证链接通，然后往下写。

## 分工与验收

| 谁 | 做什么 |
| --- | --- |
| 我 | 给骨架与卡点提示、指出错误、验收、答「为什么」 |
| 你 | 敲代码、编译、运行、讲清每层 |

**两道关**：能跑（输出对）+ 能讲（答得出上表提问）。讲不清就回上一层，不硬推。每层在 `mini-c/NOTES.md` 写 3–5 行，用自己的话。

## 时间表

| 周 | 内容 |
| --- | --- |
| 第 1 周 | L0 + L1（环境、链接、第一帧） |
| 第 2 周 | L2（Tasker + Resource + 第一个节点） |
| 第 3 周 | L3 + L4（自己的控制器 + 五种原语） |
| 第 4 周 | L5 + L6（任务闭环 + 差异表） |

## 不在本计划范围内

- 手写 CDP / WebSocket 客户端（C 里代价过高；需要页面级相对输入时，走 L3 的 `relative_move` 回调 + 上游 `CloudRelativeMove` 契约，见 [04](docs/04-云网页节点契约.md)）
- 向上游提 PR
- 把 C 代码塞进 `agent/cpp-algo`（那里只收 C++）
