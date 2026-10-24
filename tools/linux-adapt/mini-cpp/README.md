# L0：环境与最小程序

验证三件事：**SDK 能链接**、**能建出 Linux 控制器**、**能连上合成器**。不截图、不点击、不跑任务。

```text
l0_env.cpp             132 行   正式实现
l0_env_annotated.cpp   216 行   逐行注释版（预处理后 md5 与原文一致，只差注释）
CMakeLists.txt                   find_package(MaaFramework) + RPATH
```

## 环境前置

### SDK 已经在本机

```text
/opt/maafw/extract/
├── include/MaaFramework/        12 个头文件
├── bin/libMaaFramework.so       3.4 MB
├── bin/libMaaLinuxControlUnit.so   ← 运行期由框架 dlopen
├── share/cmake/                  CMake config 包
└── sample/cpp/                   官方 sample（可参照写法）
```

不需要再下载。默认路径写死在 `CMakeLists.txt`，可用 `-DMAAFW_SDK_DIR=...` 覆盖。

### 编译器与 CMake 缺失（当前阻塞点）

```text
wsl> which g++ cmake make    → 全无
```

两条路，任选：

```bash
# A. 在 WSL 装工具链（约 200 MB）
sudo apt-get update && sudo apt-get install -y build-essential cmake

# B. 完全绕开 CMake，用 Windows 侧 MinGW 直接编（只适合先看编译能不能过）
#    MinGW 的 g++ 已经在：
#    C:\Users\23983\AppData\Local\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_*\mingw64\bin\g++.exe
```

## 编译（工具链已装好）

```bash
cd tools/linux-adapt/mini-cpp
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

**一处与官方 sample 不同**：官方 sample 用 `find_package(MaaFramework CONFIG REQUIRED)` + `MaaFramework::MaaFramework`，
在本机这个 release 包上会失败——包内只有 `MaaFramework` / `MaaAgentServer` 两个 CMake config，
而导入目标把 `MaaUtils` / OpenCV / ONNXRuntime 声明为 link-dependent 依赖，它们的 config 不在包里，
CMake 生成阶段直接报「A find_package call is missing for an IMPORTED target」。

所以改成直接链 `.so`：

```cmake
target_include_directories(l0_env PRIVATE "${MAAFW_SDK_DIR}/include")
target_link_directories(l0_env PRIVATE "${MAAFW_SDK_DIR}/bin")
target_link_libraries(l0_env PRIVATE MaaFramework)
```

`libMaaFramework.so` 的 `DT_NEEDED` 已记录那些依赖库，运行时由 RPATH 解析（实测 `ldd` 0 个 not found）。

## 运行

需要合成器在跑（否则连接必然失败）：

```bash
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  ./build/l0_env /run/user/0/wayland-1
```

也可以不传参数，默认就是 `/run/user/0/wayland-1`。

## 预期输出（实测）

```text
[INFO] MaaFramework version: v5.14.3
[INFO] config: {"screencap_method": 1,"input_method": 1,"wlr_socket_path": "/run/user/0/wayland-1","use_win32_vk_code": true}
[INFO] controller created
[INFO] connected = true
[INFO] resolution unavailable
```

`resolution unavailable` **是正常的**，但原因不是「没实现」：`MaaControllerGetResolution` 返回的是
**最近一次成功截图的原始尺寸**（`ControllerAgent.cpp:232`），本程序没截图，缓存为 0 所以返回 false。
实测：截一帧后同一调用返回 `1280x720`。见 `study/L0-源码对照.md` 第 4 节。

## 判据

| # | 判据 | 说明 |
| --- | --- | --- |
| 1 | 打出 `MaaFramework version:` | 头文件版本对 + 动态库链接成功 |
| 2 | 打出 `controller created` | `config_json` 合法，ControlUnit 被找到并加载 |
| 3 | `connected = true`，退出码 0 | 真的连上了合成器 |

三条缺一条，就按 `docs/03-故障排查手册.md` 的「四层定位法」查。

## 已知卡点

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `MaaLinuxControllerCreate returned nullptr` | config 字段名拼错 / 缺必填项 / 找不到 `libMaaLinuxControlUnit.so` | 先确认 `LD_LIBRARY_PATH` 或 RPATH 指向 SDK 的 `bin` |
| `connect failed, status = 4000` | socket 路径不存在，或那个 socket 不是 sway 的 | `ls -l /run/user/*/wayland-*` 对照 |
| 运行时 `error while loading shared libraries: libMaaFramework.so` | RPATH 没生效 | `LD_LIBRARY_PATH=/opt/maafw/extract/bin ./build/l0_env` |
| 编译期 `find_package(MaaFramework) failed` | SDK 里没有 `share/cmake` | 换 `-DMAAFW_SDK_DIR`，或改用手写 `-I`/`-L`/`-l` 编译 |

## 验证记录

| 项 | 结果 |
| --- | --- |
| 语法检查（真实 12 个头文件，`-Wall -Wextra -Wpedantic`） | `SYNTAX_OK`，零警告 |
| 注释版与原文一致性（预处理后 md5） | 两个文件 `0c509be8…` 完全相同 → 只差注释 |
| 实际编译（g++ 13.3.0 + CMake 3.28.3 + Ninja 1.11.1） | **通过**，`[2/2] Linking CXX executable l0_env` |
| 实际运行（嵌套 sway，socket `wayland-1`） | **通过**：`version v5.14.3` → `controller created` → `connected = true` → 退出码 0 |
| ControlUnit 运行期依赖 | `libpipewire-0.3.so.0`、`libei.so.1`、`libwayland-client.so.0`、`libxkbcommon.so.0` 本机齐全 |
