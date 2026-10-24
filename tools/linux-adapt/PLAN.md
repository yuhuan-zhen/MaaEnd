# Linux 适配执行计划

面向云终末地网页端（Chrome 串流）在 Linux 上的控制器适配。自底向上逐层搭建，每层单独验收通过后才进入下一层。

- 基线：`origin/v2` = `a9393386`（2026-10-24）
- 分支：`feat/linux-adapt`
- 单次改动上限：**2000 行**
- 产物目录：`tools/linux-adapt/`（验收脚本 + 证据 + 文档）

## 目标与非目标

**目标**

1. 用上游 `MaaLinuxControlUnit`（不改上游）跑通云网页端的完整控制链
2. 把「相对移动失效」这条查清，给出最小代价的绕开或修复
3. 环境监测、滑索等真实任务在 Linux 上可跑
4. 保持 MXU 可视化与随时暂停的能力

**非目标**

- 不向上游提交 PR（补丁只留本地）
- 不引入新的控制器类型（继续用 `Linux-Wlroots`）
- 不改动 `MaaEnd-src` 主工作区的既有未提交改动

## 分层

| 层 | 内容 | 动手范围 | 验收 | 预算 | 状态 |
| --- | --- | --- | --- | --- | --- |
| L1 帧源 | 帧正确性、通道序、耗时 | `tools/linux-adapt/` | 8 项断言 | 200 行 | ✅ 8/8 |
| L2 输入原语 | 五种原语页面级可见性 | `tools/linux-adapt/` | 事件表 | 250 行 | 待开始 |
| L3 节点契约 | `resource_linux` 四个私有节点的实现形式 | `assets/resource_linux/` | yaw/pitch/zipline 三条路各自成立 | 60 行 | 待开始 |
| L4 Go 动作 | `rotateView` / `RelativeMoveAction` 是否需平台分支 | `agent/go-service/` | 与 L3 一致 | 150 行 | 待开始 |
| L5 任务 | 环境监测、滑索端到端 | pipeline / 探针 | 实机跑通 | 100 行 | 待开始 |
| L6 客户端 | MXU 可视化与暂停、自带入口 | 部署配置 | 可重复启动与停止 | 100 行 | 待开始 |

每层结束都更新本目录 `README.md` 的验收记录表，并单独提交。

## L1 结论（已完成）

`WlrScreencap` 输出 `(720, 1280, 3)` uint8，**BGR** 通道序（转 RGB 后与 grim 的 NCC = 1.0），耗时中位 16.2 ms（约 62 fps），静止 20 帧完全一致。

已知缺口：`MaaControllerGetResolution` 在本控制器返回 `(0, 0)`，同文件的 `start_app` 也是 `TODO`。坐标与像素目前 1:1，故无实际影响；L2 若用 resolution 做换算需先绕开。

## L2 方案：输入原语页面级验证

**要回答的问题**：五种原语是否真的到达页面、字段是否正确。核心是相对移动（`relative_move`）——它是唯一已知失效的一条。

**做法**

1. 在 nested chrome 打开本地探针页 `tools/linux-adapt/harness/input_probe.html`，页面把所有指针/键盘/滚轮事件追加到 `window.__events`，每条含 `type / clientX / clientY / movementX / movementY / button / buttons / code / deltaY`
2. 用 `MaaLinuxController` 依次下发五种原语（不进入游戏，探针页自身不产生副作用）
3. 用只读 CDP 连接（`127.0.0.1:9334`）读 `window.__events`，**不注入任何事件**
4. 输出判定表到 `evidence-l2/`

**原语与期望**

| 原语 | 下发 | 期望页面事件 |
| --- | --- | --- |
| 点击 | `touch_down(0, 640, 560)` + `touch_up(0)` | `pointerdown/pointerup`，`button=0` |
| 拖动 | `touch_down → touch_move ×n → touch_up` | 连续 `pointermove` + 按下态 |
| 键盘 | `key_down/key_up`（VK 27 与 65） | `keydown/keyup`，`code=Escape/KeyA` |
| 滚轮 | `scroll(640, 360, 0, -3)` | `wheel`，`deltaY` 符号正确 |
| **相对移动** | `relative_move(200, 0)` | 待定，见下 |

**相对移动的三种可能结果**

| 观测 | 结论 | 对 L3/L4 的影响 |
| --- | --- | --- |
| 页面完全无事件 | 合成器未转发（focus 未建立或光标贴边钳制） | 先补一次绝对移动复位；成立则 L4 只需前置复位 |
| `clientX` 变化但不产生预期 `movementX` | 事件到位、形态不符 | L3 改用 hover 绝对移动，L4 加平台分支 |
| `clientX` 不变 | sway 未移动指针 | 上游实现问题，L3 必须绕开相对移动 |

**判定标准**：前四种原语若任一失败，先修环境（合成器/权限）再继续；相对移动按上表分支记录结论，不阻塞 L3。

## 风险与回滚

- 所有验收脚本只读或只作用于**本地探针页**，不向游戏注入输入
- 产品代码改动集中在 L3/L4，各自单独提交，可单点 revert
- 证据文件不进 git（`.gitignore` 已排除 `evidence-*/`）

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
