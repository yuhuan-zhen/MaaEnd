# Wlroots 输入链路解剖

一次 `MaaControllerPostClick` 从框架 API 到页面 DOM，中间经过 6 跳。本文逐跳拆开，标出每一跳用的协议请求。
所有代码位置以函数名为准（行号会随上游改动漂移）。

## 全景

```text
pipeline 节点（Click / Swipe / ClickKey / Scroll / Custom → PostRelativeMove）
      │
      ▼
MaaFramework ControllerAgent          source/MaaFramework/Controller/ControllerAgent.cpp
      │  · 读 controller 的 feature 位，决定 Click 是否改写成 touch_down + touch_up
      │  · 坐标换算（display_* 缩放）
      ▼
LinuxControlUnitMgr                  source/MaaLinuxControlUnit/Manager/LinuxControlUnitMgr.cpp
      │  · click/swipe/touch_*/input_key/_text/scroll/relative_move 逐个转发
      ▼
WlrInput                             source/MaaLinuxControlUnit/Input/WlrInput.cpp
      │  · pointer(phase, x, y, contact) → motion_absolute + button
      │  · input_key(phase, key)        → zwp_virtual_keyboard_v1
      │  · relative_move(dx, dy)        → motion
      ▼
zwlr_virtual_pointer_v1 / zwp_virtual_keyboard_v1（Wayland 协议，客户端 → 合成器）
      ▼
sway（wlroots）   handle_virtual_pointer → seat_add_device → wlr_cursor
      │  · 有 suggested_output 时 wlr_cursor_map_input_to_output
      ▼
Chrome（Wayland 客户端）→ DOM pointermove / pointerdown / keydown / wheel
```

## 逐 API 的协议请求

| 框架 API | `WlrInput` 里的实现 | 发出的协议请求 |
| --- | --- | --- |
| `click(x,y)` | ❌ 返回 false（deprecated） | — |
| `swipe(...)` | ❌ 返回 false（deprecated） | — |
| `touch_down(contact,x,y)` | `pointer(Began, x, y, contact)` | `motion_absolute(x,y,screen_w,screen_h)` + `button(BTN_*)` + `frame` |
| `touch_move(contact,x,y)` | `pointer(Moved, x, y, contact)` | `motion_absolute(...)` + `frame` |
| `touch_up(contact)` | `pointer(Ended, 0, 0, contact)` | `button(released)` + `frame`（**不带 motion**） |
| `key_down/key_up(key)` | `input_key(phase, key)` | `zwp_virtual_keyboard_v1_key(...)` + 可能的 `modifiers` |
| `input_text(text)` | `input_text(text)` | 切 ASCII keymap 后逐字符 `key` |
| `scroll(dx,dy)` | `pointer(...)` 变体 | `axis` / `axis_discrete` + `frame` |
| `relative_move(dx,dy)` | `relative_move(dx,dy)` | **`motion(dx,dy)`** + `frame` |
| `start_app(intent)` | `LinuxControlUnitMgr::start_app` | 无（`TODO`，直接 `return false`） |

`frame` 是必须的：Wayland 用「批量提交」语义，只发 `motion` 不发 `frame`，合成器不会把这一批当成一次完整的指针更新。

## 绝对移动的坐标空间

```cpp
pointer_.reset(zwlr_virtual_pointer_manager_v1_create_virtual_pointer_with_output(
    pointer_manager_.get(), seat_.get(), output_.get()));
```

指针是**绑定到具体 output** 创建的，所以 `motion_absolute` 用的是该 output 的本地坐标：`motion_absolute(x, y, screen_w, screen_h)`，其中 `screen_w/screen_h` 来自截图/输出尺寸。

这带来两个直接后果：

1. 坐标必须是 `0 <= x < screen_w`、`0 <= y < screen_h`，**越界会被钳制**
2. 连续同向移动会把指针推到边缘，之后继续同方向移动**没有任何效果**（不是报错，是静默丢）

## 为什么 `click()` / `swipe()` 是空的

```cpp
MaaControllerFeature WlrInput::get_features() const {
    return MaaControllerFeature_UseMouseDownAndUpInsteadOfClick
         | MaaControllerFeature_UseKeyboardDownAndUpInsteadOfClick;
}
```

这两个 feature 位告诉框架「不要调我的 `click`/`swipe`/`click_key`，请拆成 down/up 两半」。指针类输入这样做的原因是：按下与抬起之间可以夹别的动作（例如按住拖动）。

`LinuxControlUnitMgr::get_features()` 只透传这两位：

```cpp
feat |= input_->get_features()
        & (MaaControllerFeature_UseMouseDownAndUpInsteadOfClick
         | MaaControllerFeature_UseKeyboardDownAndUpInsteadOfClick);
```

## `contact` 到鼠标键

```cpp
int btn = BTN_LEFT;
switch (contact) {
case 1: btn = BTN_RIGHT;  break;
case 2: btn = BTN_MIDDLE; break;
case 0:
default:;
}
```

Wlr 输入没有触摸协议，`contact` 被借用来选鼠标键。所以 `contact = 0` 是左键按下，不是「第一根手指」。

## 键盘：两套 keymap 与修饰键

- `input_key` 先 `switch_keymap(Keymap::Scancode)`，再按 `use_win32_vk_code` 决定是否把 VK 转 evdev
- `input_text` 先 `switch_keymap(Keymap::Ascii)`，按字符查表
- 修饰键（Shift/Ctrl/Alt）由 `depressed_key_modifiers` / `locked_key_modifiers` 计算，通过 `zwp_virtual_keyboard_v1_modifiers` 单独提交

**切换 keymap 是有状态的**：先发 `input_text` 再发 `input_key`，两次都会各切一次 keymap。若同一批动作混用，注意顺序。

## 相对移动为什么静默失效

### 代码（完整，共三行）

```cpp
bool WlrInput::relative_move(int dx, int dy) {
    const uint32_t event_time = WaylandHelper::get_ms();
    zwlr_virtual_pointer_v1_motion(pointer_.get(), event_time, wl_fixed_from_int(dx), wl_fixed_from_int(dy));
    zwlr_virtual_pointer_v1_frame(pointer_.get());
    return client_->process_requests();
}
```

### 请求确实发出去了（实测）

`maafw.log`：`MaaControllerPostRelativeMove(...) | leave, 0ms`，无错误；`maafw.log` 里 `relative_move is not supported` 出现 0 次。

### 但页面收不到（实测）

4 个阶段的画面变化为零，帧相关系数 0.94–1.0；同一条链路上 `motion_absolute`（悬停绝对移动）能触发视角变化（NCC 0.247）。

### 为什么静默

`MaaControllerFeature` 枚举里**没有**「支持相对移动」这一位。Manager 只能这样判断：

```cpp
auto relative_move_input = std::dynamic_pointer_cast<RelativeMoveInput>(input_);
if (!relative_move_input) {
    LogError << "relative_move is not supported by the current input method";
    return false;
}
```

`WlrInput` 继承 `RelativeMoveInput`，类型检查通过 → 错误日志永远不打 → 调用方拿到 `true`。

### 可能原因（未验证）

以下均为推断，未做最小复现：

1. 合成器侧的相对运动实现依赖指针已有焦点面，而新建的虚拟指针在首次绝对移动前没有 `wl_pointer.enter`
2. `motion` 与 `motion_absolute` 在合成器内部走不同分支，某支未处理 `suggested_output` 映射
3. 浏览器只在指针锁定或按键拖动时消费纯相对运动

**验证方法**：用 `wev` 观察页面在 `motion_absolute` 后接一次 `motion` 时是否收到 `wl_pointer.motion`。见 [03-故障排查手册](03-故障排查手册.md)。

## 指针累积与复位

MaaEnd 侧 `rotateView()`（`agent/go-service/common/charactercontroller/controller.go`）自己记账，不依赖真实光标位置：

```go
cx, cy := screenW/2, screenH/2
if absInt(cursorDX) > screenW/4 || absInt(cursorDY) > screenH/4 {
    ctx.RunAction("__CharacterControllerDeltaAltKeyDownAction", ...)
    ctx.RunAction("__CharacterControllerDeltaClickCenterAction", ...)
    ctx.RunAction("__CharacterControllerDeltaAltKeyUpAction", ...)
    cursorDX, cursorDY = 0, 0
}
fromX, fromY := cx+cursorDX, cy+cursorDY
```

三个复位节点在**不同资源层**的定义差别很大：

| 资源层 | `__CharacterControllerDeltaClickCenterAction` | 后果 |
| --- | --- | --- |
| `resource`（base） | `Click(640, 360)` | 真的把指针移回中心，累积不会无限增长 |
| `resource_adb` | `DoNothing` | 依赖 `cursorDX` 记账 + 触摸坐标差，不需要复位 |
| `resource_linux` | `DoNothing` | **指针会一路累积到边缘，之后转向静默失效** |

这就是为什么在 Linux 上要么恢复复位节点的实现，要么不能用「累积记账 + 绝对移动」这套。
