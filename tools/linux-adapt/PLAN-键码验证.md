# 键码逐个实测计划（留档）

对象：`docs/06-键码空间与VK转换.md` 里那张 24 行的表。
状态：**计划，未执行**。执行时机见第 8 节。

## 1 · 为什么要重测

第 06 篇那张表的来源是**静态解析**，不是运行期实测：

| 列 | 来源 | 性质 |
| --- | --- | --- |
| `期望 evdev` | 解析上游 `VkToEvdev.h` 的 `table[0xNN] = KEY_XXX` | 代码可查 |
| `evdev 数值` / `xkb` | 解析 `/usr/include/linux/input-event-codes.h` | 代码可查 |
| `次数` | 扫 MaaEnd `assets/resource/pipeline/` 的 JSON | 静态统计 |
| `期望 keysym` | **人工填的 US 布局对照** | ⚠️ 本文档唯一没被机器验证的一列 |

也就是说：**没有任何一列来自「真的按下去、真的收到」**。

静态解析能保证「表是这么写的」，保证不了：

1. 表里的值真的被用上（`use_win32_vk_code` 真开了没）
2. 合成器真的收到了这个键（`zwp_virtual_keyboard_v1_key` 的 keycode 换算对不对）
3. keysym 与预期一致（keymap 是 Scancode 还是 Ascii、布局是不是 US）
4. 反过来：开关关掉时**真的按错**（不验证这一条，就无法排除「正组对」只是巧合）

第 4 条尤其重要。只测正组，等于只证明「能按对」；加了负组，才证明「这个开关是起作用的原因」。

## 2 · 三层验证目标

| 层 | 验证内容 | 要不要合成器 | 要不要游戏 |
| --- | --- | --- | --- |
| A | 转换表本身：24 个 VK → evdev 与本文档一致 | 否 | 否 |
| B | 合成器收到什么：真实发送 → `wev` 抓 keysym | 是（sway） | 否 |
| C | 应用响应：游戏里按对了有反馈 | 是 | 是 |

B 层是主体。A 层防「文档抄错」，C 层抽 3~4 个键做端到端抽样即可（不必 24 个全进游戏）。

## 3 · 前置条件

| 项 | 状态 | 说明 |
| --- | --- | --- |
| `wev` | 未安装，apt 可装 `1.0.0-3` | Wayland 事件查看器，B 层核心工具 |
| `wtype` | 未安装，apt 可装 `0.4-3` | 备用发送端（见 4.4 的局限） |
| sway | 已有 | 嵌套或真实均可；需能起 `wev` |
| maafw Python | 已装 5.14.3 | 用 `LinuxController` 发键（走真实 `translate_key`） |
| 游戏 | 可选 | 只 C 层抽测时用 |

安装（一次）：

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get install -y wev wtype
```

## 4 · 待测的 24 个键值（完整表）

来源：MaaEnd `assets/resource/pipeline/` 静态统计，79 处引用、24 个键值。

| VK | 次数 | 期望 evdev | evdev 数值 | xkb keycode | 期望 keysym（US） | 按 evdev 直读会变成 |
| --- | --- | --- | --- | --- | --- | --- |
| 27 | 11 | `KEY_ESC` | 1 | 9 | `Escape` | `KEY_RIGHTBRACE`（`]`） |
| 18 | 10 | `KEY_LEFTALT` | 56 | 64 | `Alt_L` | `KEY_E` |
| 70 | 9 | `KEY_F` | 33 | 41 | `f` | `KEY_SCROLLLOCK` |
| 83 | 6 | `KEY_S` | 31 | 39 | `s` | `KEY_KPDOT` |
| 16 | 4 | `KEY_LEFTSHIFT` | 42 | 50 | `Shift_L` | `KEY_Q` |
| 87 | 4 | `KEY_W` | 17 | 25 | `w` | `KEY_F11` |
| 164 | 4 | `KEY_LEFTALT` | 56 | 64 | `Alt_L` | `KEY_PLAYPAUSE` |
| 65 | 3 | `KEY_A` | 30 | 38 | `a` | `KEY_F7` |
| 68 | 3 | `KEY_D` | 32 | 40 | `d` | `KEY_F10` |
| 82 | 3 | `KEY_R` | 19 | 27 | `r` | `KEY_KP0` |
| 69 | 2 | `KEY_E` | 18 | 26 | `e` | `KEY_NUMLOCK` |
| 160 | 2 | `KEY_LEFTSHIFT` | 42 | 50 | `Shift_L` | `KEY_CLOSECD` |
| 49 | 2 | `KEY_1` | 2 | 10 | `1` | `KEY_N` |
| 50 | 2 | `KEY_2` | 3 | 11 | `2` | `KEY_M` |
| 51 | 2 | `KEY_3` | 4 | 12 | `3` | `KEY_COMMA` |
| 52 | 2 | `KEY_4` | 5 | 13 | `4` | `KEY_DOT` |
| 112 | 2 | `KEY_F1` | 59 | 67 | `F1` | `KEY_MACRO` |
| 17 | 2 | `KEY_LEFTCTRL` | 29 | 37 | `Control_L` | `KEY_W` |
| 32 | 1 | `KEY_SPACE` | 57 | 65 | `space` | `KEY_D` |
| 48 | 1 | `KEY_0` | 11 | 19 | `0` | `KEY_B` |
| 113 | 1 | `KEY_F2` | 60 | 68 | `F2` | `KEY_MUTE` |
| 114 | 1 | `KEY_F3` | 61 | 69 | `F3` | `KEY_VOLUMEDOWN` |
| 115 | 1 | `KEY_F4` | 62 | 70 | `F4` | `KEY_VOLUMEUP` |
| 75 | 1 | `KEY_K` | 37 | 45 | `k` | `KEY_KP4` |

**注意 5 组「一对多」*：** `18` 与 `164` 都映射到 `LEFTALT`；`16` 与 `160` 都映射到 `LEFTSHIFT`。这是 `VkToEvdev.h` 的既定行为（默认左变体 + 显式 L 码），测出来两者 keysym 相同即正确，不必怀疑。

## 5 · 测试设计

### 5.1 A 层：脚本自证（2 分钟）

判据：`keycensus.py` 输出与第 4 节表**逐行一致**。

```bash
cd tools/linux-adapt
curl -s "https://raw.githubusercontent.com/MaaXYZ/MaaFramework/0fc6025c2fc224a171b57d89505e8d47acd2a8b1/source/MaaLinuxControlUnit/Input/VkToEvdev.h" \
  -o /tmp/VkToEvdev.h
python3 keycensus.py /tmp/VkToEvdev.h
```

这一层只防「文档与代码不一致」，不涉及运行期。

### 5.2 B 层：正组（24 键 × 2 种输入法）

**被测对象**：`MaaLinuxControllerCreate`（走 `translate_key`）。

**观察者**：`wev`，独立终端，只抓 `key` 事件。

**步骤**（每个键）：

1. 启动 `wev`，记录时间戳标记
2. Python 侧：`LinuxController(cfg).post_click_key(vk).wait()`
3. 从 `wev` 输出里取该次事件的 `keysym`
4. 写入 `evidence/keys.json`

配置：

```python
cfg = {"screencap_method": 1, "input_method": 1,        # Wlr 截图 + Wlr 输入
       "wlr_socket_path": "/run/user/0/wayland-1",
       "use_win32_vk_code": True}                        # ← 被测开关
```

再换 `"input_method": 2`（UInput）跑同一批，期望完全相同。

### 5.3 B 层：负组（同样 24 键）

配置只改一处：

```python
cfg["use_win32_vk_code"] = False
```

**期望**：`wev` 报出的 keysym 等于第 4 节最后一列（`]`、`e`、`Scroll_Lock`、`s`…）。

负组是这份计划的关键：它证明「正组对」来自开关，而不是巧合、也不是我们表算错。**24 键里只要有一个负组没变，就说明该键的转换根本没发生，要单独查。**

### 5.4 为什么不用 `wtype` 当发送端

`wtype` 发的是 **keysym / 文本**，不是 evdev 扫描码，它**绕过了 `translate_key`**。用它测不到被测逻辑，只能测合成器本身。

所以：`wtype` 只留作「wev 是否正常工作」的先导检查（先发个 `wtype a` 看 wev 有没有反应），主测量必须走 maafw。

### 5.5 C 层：端到端抽样（4 个键）

不必 24 个都进游戏。抽 4 个覆盖不同风险面：

| VK | 键 | 风险面 | 在游戏里的判据 |
| --- | --- | --- | --- |
| 27 | Esc | 单次点击、被游戏 UI 拦截 | 打开/关闭菜单 |
| 70 | F | MaaEnd 交互键（`AutoCollectClick`） | 出现交互提示或拾取 |
| 16 | Shift | 修饰键（无可见反馈） | 按住后跑动（需 key_down/key_up） |
| 112 | F1 | 可能与合成器/宿主热键冲突 | 游戏内帮助面板 |

F1 若被 compositor 抢走（sway 默认不抢 F1，但 WSLg 可能），记为**环境限制**而不是失败，并在文档标注。

## 6 · 脚本设计（`test_keys.py`，待写，约 120 行）

```text
参数: --socket <path> --input-method {1,2} --vk-code {true,false}
      --expect-file <json> --out <json>
流程:
  1. 读期望表（第 4 节，落成 JSON fixture）
  2. 起 wev 子进程，逐行读 stdout
  3. for vk in 期望表:
       发送 post_click_key(vk) → wait()
       从 wev 流里取该事件 keysym（带 1s 超时）
       比对 → 记 pass/fail/observed
  4. 汇总：24 条，输出 {"mode": "positive|negative", ...}
  5. 退出码：全 pass 为 0，否则 1
```

要点：

- `wev` 输出是逐行文本，用正则 `keysym: (\S+)` 抓
- 修饰键（Shift/Ctrl/Alt）点击时会连续产生 down/up 两行，只取第一条
- 每次发送前清空待读缓冲，避免上一键的残留被误配
- 超时即记 `timeout`，不静默跳过

## 7 · 记录格式（`evidence/keys.json`）

```json
{
  "env": {
    "compositor": "sway (nested)",
    "maafw": "5.14.3",
    "socket": "/run/user/0/wayland-1",
    "screencap_method": 1,
    "keymap": "US"
  },
  "runs": [
    {
      "input_method": "Wlr",
      "use_win32_vk_code": true,
      "results": [
        {"vk": 27, "expect_evdev": "KEY_ESC", "expect_keysym": "Escape",
         "observed_keysym": "Escape", "status": "pass"},
        {"vk": 70, "expect_evdev": "KEY_F", "expect_keysym": "f",
         "observed_keysym": "f", "status": "pass"}
      ],
      "summary": {"pass": 24, "fail": 0, "timeout": 0}
    }
  ]
}
```

`evidence-*/` 已在 `.gitignore` 里，原始结果不进仓库；汇总结论写回 `docs/05-实测数据.md`。

## 8 · 执行时机与依赖

| 位置 | 说明 |
| --- | --- |
| 主计划 | **L4 的入口验收**（见 `PLAN.md` L4「键码空间」卡点） |
| 前置 | L3 完成（自己的 CustomController 能跑通一个节点），这样才有「解析出来的键值 → 自己的映射」可比 |
| 依赖 | B 层不依赖游戏，可与 L3 并行提前做；C 层依赖游戏与排队时间 |
| 预计耗时 | B 层正负各 2 组 × 24 键 ≈ 15 分钟机器时间；写脚本约 1 小时；C 层看排队 |

为什么排在 L4 而不是现在：现在没有 `CustomController`，测的只是上游 `MaaLinuxController` 的行为。而 L4 真正要验的是**我自己写的那份映射**是否与上游等价——那时才有两条实现可以对照。

## 9 · 已知风险与不确定项

| # | 风险 | 处理 |
| --- | --- | --- |
| 1 | `/tmp` 在 WSL 重启后被清空（本轮已踩到一次，fixture 丢失） | fixture 与 `VkToEvdev.h` 副本放 `tools/linux-adapt/fixtures/`，别放 `/tmp` |
| 2 | modifier 状态残留（上一条用例按住了 Shift 没松开） | 每条用例前后各发一次显式 `key_up`，或每键独立进程 |
| 3 | keymap 被 `switch_keymap(Scancode)` 改过 | 记录 `wev` 报的 `keymap` 事件；读数只认发生在本键时间窗内的 |
| 4 | keysym 受布局影响（非 US 布局下标点不同） | 24 个键里只有数字/字母/ESC/F 键/修饰键，理论上与布局无关；仍记录实际布局 |
| 5 | F1~F4 被 compositor 或 WSLg 抢走 | 记为环境限制并在文档注明，不算失败 |
| 6 | UInput 需要 `/dev/uinput` 权限 | 与 Wlr 分两次跑，权限不足时明确记 `skipped` 而不是 `pass` |
| 7 | 同一 VK 映射到同一 evdev（18/164、16/160） | 期望值相同即通过，不追求区分左右 |

## 10 · 验收标准

- **A 层**：`keycensus.py` 输出与第 4 节 24 行逐字一致
- **B 层正组**：Wlr 与 UInput 各 24/24 `pass`
- **B 层负组**：24/24 与「按 evdev 直读会变成」一列一致（此项失败说明开关没生效，必须查清）
- **C 层**：4 个抽样键中 ≥3 个在游戏里产生预期反馈，未达标者写明原因
- **记录**：`evidence/keys.json` 落盘，结论回写 `docs/05-实测数据.md` 新增一节「键码实测」

## 11 · 命令清单（执行时照抄）

```bash
# 0. 装工具
apt-get install -y wev wtype

# 1. A 层
cd tools/linux-adapt
curl -s "https://raw.githubusercontent.com/MaaXYZ/MaaFramework/0fc6025c2fc224a171b57d89505e8d47acd2a8b1/source/MaaLinuxControlUnit/Input/VkToEvdev.h" \
  -o fixtures/VkToEvdev.h
python3 keycensus.py fixtures/VkToEvdev.h

# 2. 起合成器（若无现成的）
export XDG_RUNTIME_DIR=/run/user/0
printf 'output * bg #101010 solid_color\n' > /tmp/sway.conf
setsid sway -c /tmp/sway.conf > /tmp/sway.log 2>&1 < /dev/null &

# 3. B 层正组（另开终端跑 wev）
wev | grep --line-buffered "keysym" &
python3 test_keys.py --socket /run/user/0/wayland-1 --input-method 1 --vk-code true  --out /tmp/keys-pos-wlr.json
python3 test_keys.py --socket /run/user/0/wayland-1 --input-method 2 --vk-code true  --out /tmp/keys-pos-uinput.json

# 4. B 层负组
python3 test_keys.py --socket /run/user/0/wayland-1 --input-method 1 --vk-code false --out /tmp/keys-neg-wlr.json

# 5. 收尾（不留后台进程）
pkill wev; pkill sway
```

## 12 · 与本计划相关的文档

| 主题 | 位置 |
| --- | --- |
| 键码空间原理与源码地址 | [`docs/06-键码空间与VK转换.md`](docs/06-键码空间与VK转换.md) |
| 24 键统计脚本 | [`keycensus.py`](keycensus.py) |
| 主学习计划 L4 | [`PLAN.md`](PLAN.md) |
| 上游实现地址总表 | [`study/L0-源码对照.md`](study/L0-源码对照.md) |
| 实测数据归档 | [`docs/05-实测数据.md`](docs/05-实测数据.md) |
