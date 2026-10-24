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

## 编译（工具链就位后）

```bash
cd tools/linux-adapt/mini-cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

## 运行

需要合成器在跑（否则连接必然失败）：

```bash
XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
  ./build/l0_env /run/user/0/wayland-1
```

也可以不传参数，默认就是 `/run/user/0/wayland-1`。

## 预期输出

```text
[INFO] MaaFramework version: v5.14.3
[INFO] config: {"screencap_method": 1,"input_method": 1,"wlr_socket_path": "/run/user/0/wayland-1","use_win32_vk_code": true}
[INFO] controller created
[INFO] connected = true
[INFO] resolution = 0x0
```

`resolution = 0x0` **是正常的**：Linux 控制器的 `MaaControllerGetResolution` 尚未实现（见 `docs/01`）。

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
| 实际编译链接 | **未验证**（WSL 无工具链） |
| 实际运行连接 | **未验证**（依赖上一条） |
