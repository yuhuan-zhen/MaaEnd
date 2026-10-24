# L1 帧源验收 · 精读

对象：`tools/linux-adapt/l1_screencap.py`（195 行）
注释版：[`study/l1_screencap_annotated.py`](l1_screencap_annotated.py)（400 行，**AST 与原文完全一致**，只加注释没改语句）

## 这份文件在干什么

一句话：**证明 MaaFramework 在 Linux 上截出来的画面是正确的**。

为什么只测这一件事：后面所有识别（模板匹配、OCR）都建立在截图上。截图错一个尺寸或错一个通道顺序，不会报错，只会让识别率莫名变低。所以先把它单独钉死。

流程只有五步：

```text
创建 LinuxController（说清楚用哪种截图/输入方式）
   ↓ post_connection().wait()
连上 sway（Wayland 合成器）
   ↓ post_screencap().wait().get() × 20
拿到 20 张 numpy 矩阵（BGR，720×1280×3）
   ↓
量四件事：尺寸 / 通道序 / 耗时 / 稳定性
   ↓ 与 grim 抓的同一画面比 NCC
输出 8 项 PASS/FAIL + l1.json
```

## 怎么读

1. 先读本文的「术语表」和「分块精读」，理解每段在防什么坑
2. 再打开注释版，从 `def main()` 往下顺着读（前四个函数是工具，可以先跳过）
3. 最后做文末 5 道自测题，答不上来说明对应块没读到

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

### 块 1 · 导入与依赖（第 16–31 行）

这段没有逻辑，但每一行都对应一个「依赖从哪来」的问题：

| 导入 | 来自哪个包 | 本仓库哪声明 |
| --- | --- | --- |
| `numpy` | numpy | `[dependency-groups] images`（`numpy>=2.5`） |
| `PIL` | **pillow** | `images`（`pillow>=13.0`） |
| `LinuxController` | **maafw**（import 名 ≠ 包名） | `pipeline`（`maafw>=5.12`，锁 5.14.3） |

`SCREENCAP_WLR = 1` 和 `INPUT_WLR = 1` 这两个 `1` 不是随手写的，是 C 枚举值，出处见 [FW-2.4] 的两张表。写错数字不会报错，会静默换成另一种方式（比如把 `4` 当截图方式 → 变成 PipeWire，直接连不上）。

### 块 2 · `ncc()`（第 34–41 行）

先把两图各自减掉自己的均值，再算余弦相似度。两步的意义：

- **减均值**：去掉整体亮度差异（同一画面调了亮度也能匹配上）
- **除模长**：把结果归一化到 −1~1，与图片大小、对比度无关

两个细节：`astype(np.float64)` 必须在减法之前，否则 `uint8` 相减会往下溢出（`0 - 5` 变成 `251`）；分母为 0 时返回 `nan` 而不是崩掉，因为纯色图（减均值后全 0）在真实场景里会出现。

### 块 3 · `channel_means()`（第 44–45 行）

`img[:, :, i]` 取第 i 个颜色平面求均值。它的用途就一个：**判断通道序**。同一画面按 BGR 和按 RGB 读，得到的三个数是**倒序**的（实测 `[146.9, 138.7, 122.0]` vs `[122.0, 138.7, 146.9]`），一眼可辨。

### 块 4 · `grim_capture()`（第 48–55 行）

为什么要外部工具：如果我们的截图路径自己缩放错了，**自己跟自己比发现不了**。grim 用同一个 `zwlr-screencopy` 协议但由别人实现，所以它的输出可以当标准答案。

`check=True` 保证「命令失败就抛异常」；`stdout/stderr` 丢进 `DEVNULL` 是为了不让可选步骤污染验收日志；最后还是 `exists()` 再看一眼——退出码 0 但没写文件的情况真实存在。

### 块 5 · `save_png()`（第 58–61 行）

`img[:, :, ::-1]` 是 numpy 的倒序切片，把 BGR 翻成 RGB。这一步纯为**人眼看图**（PIL 认为数据是 RGB）。如果忘了翻，PNG 里天空是橙的、草地是紫的——代码不报错，只有人看得出来。

### 块 6 · 参数、输出目录、结果对象（第 64–73 行）

三件事：命令行参数（`--socket` / `--n` / `--out`，都有默认值所以能空参跑）、证据目录（按**脚本所在目录**拼，不按当前工作目录）、结果对象（`checks` 存逐项布尔，`ok` 存汇总）。

`result` 一开始就带 `"ok": False`，是「默认失败」的写法：任何一步异常退出时，落盘的 JSON 都不会误报成功。

### 块 7 · 创建控制器并连接（第 76–99 行）

`cfg` 就是 [FW-2.2] 里 `MaaLinuxControllerCreate` 的 `config_json`，Python 侧收 dict。四个字段：

| 字段 | 值 | 含义与出处 |
| --- | --- | --- |
| `screencap_method` | `1` | Wlr，走 `zwlr-screencopy`；[FW-2.4] Linux Screencap 表 |
| `input_method` | `1` | Wlr，走 wlr virtual pointer；[FW-2.4] Linux Input 表 |
| `wlr_socket_path` | `/run/user/0/wayland-1` | 嵌套 sway 的 socket；`0` 是 root uid，`1` 是因为 `wayland-0` 被 WSLg 占用 |
| `use_win32_vk_code` | `true` | 键码空间：`true` = 传 Win32 VK（27 = Esc）由框架转 evdev |

连接是异步的：`post_connection()` 立刻返回 Job，`job.wait()` 才阻塞到结束，`job.succeeded` 才是结论。失败时**先把 result 落盘再退出**，这样事后能看到当时用的 socket 和错误原文。

### 块 8 · resolution 这个坑（第 102–107 行）

`ctrl.resolution` 在本控制器上返回 **`(0, 0)`**，而帧明明是 1280×720。原因：Linux 控制器的 `MaaControllerGetResolution` 尚未实现完整（同文件的 `start_app` 也是 `TODO`）。

现在无影响（没设 `display_*`，坐标与像素 1:1），但任何「拿 resolution 去换算」的代码都会拿到 0，所以这里必须单独记录而不是假设它正确。

### 块 9 · 抓帧与统计（第 110–145 行）

`post_screencap().wait().get()` 是 MaaFramework 的固定三段式：提交 → 等 → 取。`get()` 在 `wait()` 之前拿到的是空结果。

统计口径：`min / median / p95 / max` 四个数一起看。**判定用中位数**——平均值会被偶尔一帧卡顿带偏。`min(len-1, int(len*0.95))` 是防越界，样本少时下标会算到 `len`。

稳定性用「每帧整体均值的标准差」：画面静止时应该几乎为 0（实测 **0.0**）。标准差大说明画面在变（那这一轮耗时就不代表真实负载），或截图有随机噪声。

### 块 10 · 通道序交叉验证与判定（第 148–191 行）

对照逻辑是**两个假设赛跑**：

| 假设 | 做法 | 实测 NCC |
| --- | --- | --- |
| A：帧是 BGR（binding 声明） | 翻成 RGB 后与 grim 比 | **1.0** |
| B：帧本来就是 RGB | 原样与 grim 比 | 0.757 |

A 明显高于 B，通道序被自证。`checks["bgr_confirmed"]` 就是「A > B」这个断言。`matches_grim > 0.90` 是「抓的是同一画面」的下限。

判定设计原则：**每项单独可读，不做复合条件**。所以 `resolution_1280x720` 里带了一个 `or`——resolution 不可信时退一步用帧的真实 shape。没拿到 grim 对照时，那两项布尔**不加入 checks**，避免被算成本次失败。

退出码三分：`0` 通过、`1` 环境或参数错、`2` 验收不通过。区分它们是为了让调用方知道「该修环境还是该修代码」。

## 函数索引

| 函数 | 作用 | 参数 | 返回 | 谁调用 | 注意点 |
| --- | --- | --- | --- | --- | --- |
| `ncc` | 两图相似度 | 两个 numpy 矩阵 | `-1~1` 的 float，或 `nan` | `main`（通道校验） | 必须先升 float64，否则 uint8 溢出 |
| `channel_means` | 三通道均值 | 图像矩阵 | 3 个 float 的列表 | `main`（通道序判断） | 顺序按矩阵通道序，不自动识别 BGR/RGB |
| `grim_capture` | 外部抓参考帧 | 输出路径 | bool 成功与否 | `main` | 失败不算验收失败，只标记 unavailable |
| `save_png` | BGR 矩阵存 PNG | 矩阵、路径、是否翻转 | 无 | `main` | 默认翻转；灰度图不翻 |
| `main` | 全流程与判定 | 无（读命令行） | 退出码 0/1/2 | 脚本入口 | 每步失败都先落盘再退出 |

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
4. `resolution_1280x720` 这一项为什么要 `or` 一个「帧 shape 判断」？
5. 退出码 `0 / 1 / 2` 分别代表什么，为什么要把它们分开？

<details>
<summary>答案</summary>

1. `post_*` 只是提交任务并立刻返回 Job；不等就取结果，拿到的是空/未完成状态。
2. `uint8` 相减会向下溢出（`0-5` 变 `251`），必须在减法前升到浮点。
3. 前者证明「帧确实是 BGR，翻成 RGB 后与标准答案逐像素一致」；后者说明「若把它当 RGB 用」相似度明显更低，从而排除「本来就是 RGB」这个假设。两者对比才构成自证。
4. 因为本控制器的 `resolution` 实测返回 `(0, 0)`（API 未补全），不能作为唯一依据；帧的真实 shape 才是可靠事实。
5. `0` 通过、`1` 环境/参数错（socket 连不上、配置非法）、`2` 验收不通过（帧不对）。分开是为了让调用方区分「修环境」还是「修代码」。

</details>

## 运行

```bash
# 仓库口径（默认组已含 numpy / pillow / maafw）
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  uv run python tools/linux-adapt/l1_screencap.py --n 20

# 本机 WSL 无 uv 时（系统 Python 3.12 + 已装等价版本依赖）
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  python3 tools/linux-adapt/l1_screencap.py --n 20
```

产物在 `evidence-l1/`：`l1.json`、`frame-bgr2rgb.png`、`ref-grim.png`（均已 gitignore）。
