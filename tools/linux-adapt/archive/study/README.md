# L1 帧源验收 · 精读

对象：`tools/linux-adapt/l1_screencap.py`（180 行）
工具库：`tools/linux-adapt/harness/common.py`（65 行，L1 与 L2 共用）
注释版：
- [`study/l1_screencap_annotated.py`](l1_screencap_annotated.py)（290 行，**AST 与原文完全一致**，只加注释没改语句）
- [`study/harness_common_annotated.py`](harness_common_annotated.py)（110 行，同上）

> 两份注释版顶部有一行 `# pyright: reportMissingImports=false, ...`：它们只是**阅读副本**，
> 依赖（`maa` / `numpy` / `pillow`）装在 WSL 的 uv 环境里，读代码的这台 Windows 解释器上没有，
> 不静音会在编辑器里满屏红色。这是注释，不影响 AST 一致性，也不影响源文件自身的检查。

## 这份文件在干什么

一句话：**证明 MaaFramework 在 Linux 上截出来的画面是正确的**。

为什么只测这一件事：后面所有识别（模板匹配、OCR）都建立在截图上。截图错一个尺寸或错一个通道顺序，不会报错，只会让识别率莫名变低。所以先把它单独钉死。

流程：

```text
创建 LinuxController（说清楚用哪种截图/输入方式）
   ↓ post_connection().wait()
连上 sway（Wayland 合成器）
   ↓ 记录 resolution_api / start_app 两个「记录项」（不判定）
   ↓ post_screencap().wait().get() × 20
拿到 20 张 numpy 矩阵（BGR，720×1280×3）
   ↓
量四件事：尺寸 / 通道序 / 耗时 / 稳定性
   ↓ 与 grim 抓的同一画面比 NCC
输出 8 项判定 PASS/FAIL + 2 项记录 + l1.json
```

## 判定项与记录项

这是本层最重要的一条约定，改代码时别破坏它。

| 类别 | 项 | 是否参与 `result["ok"]` |
| --- | --- | --- |
| 判定（8） | `connect` / `shape_1280x720` / `shape_hw3` / `not_blank` / `stable` / `fast_enough` / `matches_grim` / `bgr_confirmed` | 是 |
| 记录（2） | `resolution_api` / `start_app` | 否 |

为什么拆：`ctrl.resolution` 在本控制器返回 `(0, 0)`，以前用「帧 shape 兜底」让它通过，等于把「上游 API 未补全」这个事实藏在一条恒真的断言里。现在 shape 单独判，resolution 只记录——**记录项可以一直是坏消息，但不会污染通过率**。

## 怎么读

1. 先读本文的「术语表」和「分块精读」，理解每段在防什么坑
2. 再打开 `l1_screencap_annotated.py`，从 `def main()` 往下顺着读
3. 工具函数（ncc / channel_means / grim_capture / save_png / default_wlr_socket）已经抽到 `harness/common.py`，要看它们的讲解就打开 `harness_common_annotated.py`
4. 最后做文末 5 道自测题，答不上来说明对应块没读到

## 术语表

| 词 | 含义 | 为什么这里在意 |
| --- | --- | --- |
| Controller 控制器 | MaaFramework 里负责「截图 + 输入」的对象，一个 Tasker 绑一个 | 本文件测的就是它的截图能力 |
| Job | 异步操作句柄。`post_xxx()` 只提交，`.wait()` 才等结果 | 少写 `wait()` 就永远拿到空结果 |
| BGR / RGB | 三个颜色分量的排列顺序。MaaFramework 是 BGR，PIL 是 RGB | 搞反 → 红蓝互换，模板全失配 |
| NCC | 归一化互相关，−1~1，1 = 完全同一画面 | 比「逐像素相等」更耐噪，适合当相似度尺子 |
| grim | wlroots 系合成器的官方截图小工具，用同一个截图协议 | 当「标准答案」，避免自证 |
| Wayland socket | 与合成器通信的本地文件，如 `/run/user/0/wayland-1` | 连不上它就什么都做不了 |
| 合成器 | 这里指 sway，负责管理窗口与画面输出 | 我们控制的是它里面的 Chrome 窗口 |
| uint8 | 0~255 的 8 位整数，图像的标准存储类型 | 算均值前不升精度会溢出 |

## 分块精读

> 各块按功能划分，不标死行号（重构后行号会漂）；注释版里每段都有就近说明。

### 块 1 · 导入与依赖

这段没有逻辑，但每一行都对应一个「依赖从哪来」的问题：

| 导入 | 来自哪个包 | 本仓库哪声明 |
| --- | --- | --- |
| `numpy` | numpy | `[dependency-groups] images`（`numpy>=2.5`） |
| `PIL` | **pillow** | `images`（`pillow>=13.0`） |
| `LinuxController` | **maafw**（import 名 ≠ 包名） | `pipeline`（`maafw>=5.12`，锁 5.14.3） |
| `harness.common` | 本仓库 `tools/linux-adapt/harness/` | 无第三方依赖 |

`SCREENCAP_WLR = 1` 和 `INPUT_WLR = 1` 这两个 `1` 不是随手写的，是 C 枚举值，出处见 [FW-2.4] 的两张表。写错数字不会报错，会静默换成另一种方式（比如把 `4` 当截图方式 → 变成 PipeWire，直接连不上）。

`from harness.common import (...)` 之所以能直接导入：以脚本方式运行时 `sys.path[0]` 就是 `tools/linux-adapt/`，`harness` 作为命名空间包被解析。

### 块 2 · 参数与 socket 默认值

`--socket` 的默认值不再写死 `/run/user/0/wayland-1`，而是 `default_wlr_socket()`：取 `$XDG_RUNTIME_DIR` + `$WAYLAND_DISPLAY`，任一缺失才回退到 `wayland-0`。

改这一处的理由很实际：写死 uid=0 意味着换用户、换发行版、换显示实例（`wayland-0` / `wayland-1`）都要改代码，而且 L2/L5 会把同一个硬编码再抄两遍。

`out_dir` 按**脚本所在目录**拼，不按当前工作目录：从仓库根目录跑和从 `tools/linux-adapt/` 跑，证据都落在同一处。

### 块 3 · 创建控制器并连接

`cfg` 就是 [FW-2.2] 里 `MaaLinuxControllerCreate` 的 `config_json`，Python 侧收 dict：

| 字段 | 值 | 含义与出处 |
| --- | --- | --- |
| `screencap_method` | `1` | Wlr，走 `zwlr-screencopy`；[FW-2.4] Linux Screencap 表 |
| `input_method` | `1` | Wlr，走 wlr virtual pointer；[FW-2.4] Linux Input 表 |
| `wlr_socket_path` | 默认由环境变量推导 | 嵌套 sway 的 socket |
| `use_win32_vk_code` | `true` | 键码空间：`true` = 传 Win32 VK（27 = Esc）由框架转 evdev |

连接是异步的：`post_connection()` 立刻返回 Job，`job.wait()` 才阻塞到结束，`job.succeeded` 才是结论。失败时**先把 result 落盘再退出**，这样事后能看到当时用的 socket 和错误原文。

### 块 4 · 两个记录项

| 记录项 | 取法 | 现状 |
| --- | --- | --- |
| `resolution_api` | `ctrl.resolution` | 返回 `(0, 0)`：Linux 控制器的 `MaaControllerGetResolution` 尚未实现完整 |
| `start_app` | **不调用**，只写 `{"probed": False, "note": ...}` | 上游 `LinuxControlUnit` 的 `start_app` 仍是 `TODO` |

`start_app` 刻意不探测：调用一个已知是 `TODO` 的实现只会拿到失败，还会在日志里制造噪声。留一条记录给 L5，是为了让 L5 在写启停逻辑前就知道「这里没有」。

### 块 5 · 参考帧与抓帧

`grim_capture()` 拿不到 grim 时**不算失败**，只是少两项交叉验证——`checks` 里那两项会自动不加入，避免环境缺工具被判成代码错。

`post_screencap().wait().get()` 是 MaaFramework 的固定三段式：提交 → 等 → 取。`get()` 在 `wait()` 之前拿到的是空结果。

统计口径 `min / median / p95 / max` 四个数各防一件事：

| 统计量 | 防什么 |
| --- | --- |
| `min` | 协议本身的开销上限（热路径最快多快） |
| `median` | 真实可用帧率，**判定只看它**（平均值会被偶发慢帧带偏） |
| `p95` | 抖动上限（游戏里偶发卡顿会不会拖垮识别节奏） |
| `max` | 离群值（首次分配缓冲、GC 之类） |

`min(len-1, int(len*0.95))` 是防越界：样本少时下标会算到 `len`。

### 块 6 · 稳定性与落盘

稳定性用「每帧整体均值的标准差」：画面静止时应几乎为 0（实测 **0.0**）。标准差大说明画面在变（这一轮耗时就不代表真实负载），或截图有随机噪声。

落盘只用**第一帧**：静止画面下 20 帧应完全一致，用第一帧能避免把「偶发花屏帧」当成常态结论。

### 块 7 · 通道序交叉验证

对照逻辑是**两个假设赛跑**：

| 假设 | 做法 | 实测 NCC |
| --- | --- | --- |
| A：帧是 BGR（binding 声明） | 翻成 RGB 后与 grim 比 | **1.0** |
| B：帧本来就是 RGB | 原样与 grim 比 | 0.757 |

A 明显高于 B，通道序被自证。`checks["bgr_confirmed"]` 就是「A > B」这个断言；`matches_grim > 0.90` 是「抓的是同一画面」的下限。

注意这是**独立实现之间的对照**：grim 不是我们写的，所以「自己跟自己比发现不了缩放错」这个陷阱被绕开了。

### 块 8 · 判定

判定设计原则：**每项单独可读，不做复合条件**。

`shape_1280x720` 只看 `first.shape`，不再 `or` 上 `resolution`。`not_blank` 上下界一起判（纯黑与过曝都是「没拿到帧」）。`fast_enough` 用 500 ms 这个很宽松的阈值，只用来抓「完全没走 wlroots 协议」这类异常。

退出码三分：`0` 通过、`1` 环境或参数错、`2` 验收不通过。区分它们是为了让调用方知道「该修环境还是该修代码」。

## 函数索引

| 函数 | 所在文件 | 作用 | 注意点 |
| --- | --- | --- | --- |
| `main` | `l1_screencap.py` | 全流程与判定 | 每步失败都先落盘再退出 |
| `default_wlr_socket` | `harness/common.py` | 环境变量 → socket 路径 | `WAYLAND_DISPLAY` 是绝对路径时直接用 |
| `ncc` | `harness/common.py` | 两图相似度 | 必须先升 float64，否则 uint8 溢出 |
| `channel_means` | `harness/common.py` | 三通道均值 | 顺序按矩阵通道序，不自动识别 BGR/RGB |
| `grim_capture` | `harness/common.py` | 外部抓参考帧 | 失败不算验收失败，只标记 unavailable |
| `save_png` | `harness/common.py` | BGR 矩阵存 PNG | 默认翻转；灰度图不翻 |

## 文档对照表

| 标记 | 文档 | 用在哪 |
| --- | --- | --- |
| [FW-2.1] | [MaaFramework 2.1 集成文档](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.1-%E9%9B%86%E6%88%90%E6%96%87%E6%A1%A3.md) | Python binding 地位（官方支持、标准化接口、协议解析全 ✔️）、PyPI 包名 `MaaFw` |
| [FW-2.2] | [MaaFramework 2.2 集成接口一览](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.2-%E9%9B%86%E6%88%90%E6%8E%A5%E5%8F%A3%E4%B8%80%E8%A7%88.md) | `MaaLinuxControllerCreate(config_json)` 签名；异步 Job 语义 |
| [FW-2.4] | [MaaFramework 2.4 控制方式说明](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.4-%E6%8E%A7%E5%88%B6%E6%96%B9%E5%BC%8F%E8%AF%B4%E6%98%8E.md) | `1`/`4` 这些枚举值的出处：Linux Screencap（Wlr=1、PipeWire=4）、Linux Input（Wlr=1、UInput=2、Libei=4） |
| [FW-3.3] | [MaaFramework 3.3 ProjectInterface V2](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.3-ProjectInterfaceV2%E5%8D%8F%E8%AE%AE.md) | `controller.type` 闭集、`display_*` 缩放字段（本脚本刻意不设，保持 1:1） |
| [BIND] | [binding 源码 `maa/controller.py`](https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/controller.py) | `LinuxController.__init__(config)`、`post_screencap()`、`resolution` 的实现 |
| [IMG-BUF] | [binding `maa/buffer.py`](https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/buffer.py) | 「图像格式为 BGR，与 OpenCV 兼容」这句声明的出处 |
| [NUMPY] | [NumPy 索引与切片](https://numpy.org/doc/stable/user/basics.indexing.html) | `img[:, :, i]`、`img[:, :, ::-1]` 的含义 |
| [PIL] | [Pillow `Image.fromarray` / `save`](https://pillow.readthedocs.io/en/stable/reference/Image.html) | 为什么落盘前要转 RGB、为什么要 `uint8` |
| [GRIM] | [grim 官方仓库](https://git.sr.ht/~emersion/grim) | 参考帧工具；与 `zwlr-screencopy` 同协议 |
| [WLR] | [wlr-screencopy 协议说明](https://wayland.app/protocols/wlr-screencopy-unstable-v1) | 「同一路输出、同一协议」的技术依据 |
| [PLAN] | 本仓库 `tools/linux-adapt/PLAN.md` | L1 的验收标准与六层计划 |
| [L1] | 本仓库 `tools/linux-adapt/README.md` | 本次实测数据（8/8、16.2 ms、NCC 1.0） |
| [UV] | 本仓库 `pyproject.toml` + PR [#4867](https://github.com/MaaEnd/MaaEnd/pull/4867) / [#6649](https://github.com/MaaEnd/MaaEnd/pull/6649) | 依赖分组、`uv run` 口径、Python 3.14 下限 |

## 自测 5 题

1. 为什么必须 `post_screencap().wait().get()`，不能省掉 `wait()`？
2. `ncc()` 里为什么先 `astype(np.float64)` 再做减法？
3. `NCC(BGR→RGB)=1.0`、`NCC(原样)=0.757`，这两个数分别证明了什么？
4. `resolution_api` 为什么只记录、不参与判定？把它改成判定项会怎样？
5. 退出码 `0 / 1 / 2` 分别代表什么，为什么要把它们分开？

<details>
<summary>答案</summary>

1. `post_*` 只是提交任务并立刻返回 Job；不等就取结果，拿到的是空/未完成状态。
2. `uint8` 相减会向下溢出（`0-5` 变 `251`），必须在减法前升到浮点。
3. 前者证明「帧确实是 BGR，翻成 RGB 后与标准答案逐像素一致」；后者说明「若把它当 RGB 用」相似度明显更低，从而排除「本来就是 RGB」这个假设。两者对比才构成自证。
4. 因为它实测返回 `(0, 0)`，是上游 API 未补全，不是我们这层能修的事。若改成判定项，L1 会永远 FAIL；若用 `or` 兜底让它恒真，又会把缺口藏起来。记录项是第三种选择：事实留着，通过与否不受它影响。
5. `0` 通过、`1` 环境/参数错（socket 连不上、配置非法）、`2` 验收不通过（帧不对）。分开是为了让调用方区分「修环境」还是「修代码」。

</details>

## 运行

```bash
# socket 默认从环境变量推导，所以只要这两个变量在环境里即可
export XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1

# 仓库口径（默认组已含 numpy / pillow / maafw）
uv run python tools/linux-adapt/l1_screencap.py --n 20

# 本机 WSL 无 uv 时（系统 Python 3.12 + 已装等价版本依赖）
python3 tools/linux-adapt/l1_screencap.py --n 20
```

产物在 `evidence-l1/`：`l1.json`、`frame-bgr2rgb.png`、`ref-grim.png`（均已 gitignore）。

> 本次重构（抽 `harness/common.py`、socket 默认值改环境变量、resolution 拆成记录项）**改的是代码结构，没有重跑验收**；`README.md` 里 8/8 与 16.2 ms 仍是上一次实测的数字，重跑后应更新。
