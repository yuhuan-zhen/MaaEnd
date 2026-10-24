# L0 详读（构建部分）：CMakeLists 的每一行在干什么

对象：`mini-cpp/CMakeLists.txt`（31 行）；注释版 `mini-cpp/CMakeLists_annotated.txt`。

## 这份文件解决什么问题

一句话：**告诉编译器「头文件在哪、库在哪、编成什么、运行时去哪找 .so」**。

手动编译也能做到，但四条命令容易记错：

```bash
g++ -std=c++20 -I/opt/maafw/extract/include -c l0_env.cpp -o l0_env.o
g++ l0_env.o -L/opt/maafw/extract/bin -lMaaFramework -o l0_env
LD_LIBRARY_PATH=/opt/maafw/extract/bin ./l0_env     # 不设就跑不起来
```

CMake 做的事就是把这四条变成一次 `cmake --build`，并且把第三行固化成 RPATH。

## 四个关键概念

### ① `find_package(X CONFIG)` 到底找了什么

它去找 `<prefix>/share/cmake/X/XConfig.cmake`。本机确实有这个文件：

```text
/opt/maafw/extract/share/cmake/MaaFramework/MaaFrameworkConfig.cmake
/opt/maafw/extract/share/cmake/MaaFramework/MaaFramework-relwithdebinfo.cmake
```

配置文件里定义了「导入目标」`MaaFramework::MaaFramework`，里面已经写好了头文件目录和 `.so` 的绝对路径。所以链接时只需要写目标名，不用写 `-I` / `-L`。

`<prefix>` 从哪来？就是 `CMAKE_PREFIX_PATH`。我们用 `list(APPEND CMAKE_PREFIX_PATH "${MAAFW_SDK_DIR}")` 把 SDK 根目录塞进去。

**这就是为什么 `-DMAAFW_SDK_DIR=...` 能生效**——换 prefix，`find_package` 就换个地方找。

### ② `CONFIG` 与 `REQUIRED` 两个词

| 词 | 含义 | 不加会怎样 |
| --- | --- | --- |
| `CONFIG` | 只找 `<Name>Config.cmake`，不去跑 `FindXXX.cmake` 脚本 | 可能匹配到 CMake 自带的同名 Find 模块，行为不同 |
| `REQUIRED` | 找不到就立刻失败 | 配置阶段顺利通过，编译时爆一堆「找不到头文件」 |

### ③ RPATH：为什么程序编好了还跑不起来

`libMaaFramework.so` 在 `/opt/maafw/extract/bin` 下，**不在**系统库目录（`/usr/lib` 等）。动态链接器默认只在那几个目录找，所以直接运行会报：

```text
error while loading shared libraries: libMaaFramework.so
```

三种解法：

| 解法 | 写法 | 评价 |
| --- | --- | --- |
| **RPATH（我们用的）** | `set_target_properties(... BUILD_RPATH ...)` | 编进 ELF 里，以后直接运行就能跑 |
| 环境变量 | `LD_LIBRARY_PATH=... ./l0_env` | 每次都要带，容易忘 |
| 装进系统 | `cp *.so /usr/local/lib && ldconfig` | 污染系统，且版本升级时要重来 |

还有一个更隐蔽的依赖：Linux 控制器的 **ControlUnit 是独立 `.so`**（`libMaaLinuxControlUnit.so`），由框架在**运行期** `dlopen` 加载。所以 RPATH 必须指向 `bin` 整个目录，而不是只链一个库文件。

### ④ `PRIVATE` 是什么意思

```cmake
target_link_libraries(l0_env PRIVATE MaaFramework::MaaFramework)
```

`PRIVATE` = 这个依赖只给 `l0_env` 自己用。如果将来别的 target 依赖 `l0_env`（比如做成库），它不会自动继承 MaaFramework 的头文件路径。

对比 `PUBLIC`（自己用 + 传染给依赖者）与 `INTERFACE`（自己不用，只给依赖者）。可执行文件用 `PRIVATE` 是标准做法。

## 逐块讲解

### 块 1 · 版本与工程（第 1–6 行）

```cmake
cmake_minimum_required(VERSION 3.20)
project(maaend_linux_adapt_l0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
```

- `LANGUAGES CXX` 只启用 C++，省掉找 C/Fortran 编译器的开销
- `STANDARD_REQUIRED ON` 让「编译器不支持 C++20」变成配置期错误，而不是静默降级
- `EXTENSIONS OFF` 关掉 `gnu++20` 之类扩展，避免写出「只在 GCC 上成立」的代码

### 块 2 · SDK 定位与检查（第 8–22 行）

```cmake
if(NOT DEFINED MAAFW_SDK_DIR)
    set(MAAFW_SDK_DIR "/opt/maafw/extract")
endif()

if(NOT EXISTS "${MAAFW_SDK_DIR}/include/MaaFramework/MaaAPI.h")
    message(FATAL_ERROR "...")
endif()
```

**为什么要在配置阶段就检查头文件存在**：否则错误会推迟到编译，表现成「找不到 `MaaFramework/MaaAPI.h`」，而人第一反应是「我 include 写错了」，实际是路径没配。

### 块 3 · 找包与链接（第 24–28 行）

```cmake
list(APPEND CMAKE_PREFIX_PATH "${MAAFW_SDK_DIR}")
find_package(MaaFramework CONFIG REQUIRED)
add_executable(l0_env l0_env.cpp)
target_link_libraries(l0_env PRIVATE MaaFramework::MaaFramework)
```

注意 `APPEND`：直接 `set(CMAKE_PREFIX_PATH ...)` 会覆盖 CMake 自带路径，导致其他包找不到。

### 块 4 · RPATH 与告警（第 30–31 行）

```cmake
set_target_properties(l0_env PROPERTIES
    BUILD_RPATH "${MAAFW_SDK_DIR}/bin"
    INSTALL_RPATH "${MAAFW_SDK_DIR}/bin")
target_compile_options(l0_env PRIVATE -Wall -Wextra -Wpedantic)
```

`BUILD_RPATH` 管构建目录里的可执行文件，`INSTALL_RPATH` 管 `cmake --install` 之后的那份。两个都设，免得换了运行位置就失效。

## 指令索引

| 指令 | 作用 | 参数要点 | 不加会怎样 |
| --- | --- | --- | --- |
| `cmake_minimum_required` | 声明最低 CMake 版本 | 低于它会得到策略告警 | 新版 CMake 可能按旧策略处理，行为难预测 |
| `project` | 定义工程与语言 | `LANGUAGES CXX` 只启 C++ | CMake 会去找 C 编译器 |
| `set(CMAKE_CXX_STANDARD)` | 指定 C++ 标准 | 与 cpp-algo 一致用 20 | 默认可能是 17 或更早，`constexpr` 等写法受限 |
| `if(NOT EXISTS ...)` | 配置阶段的前置检查 | 检查头文件而非目录 | 错误推迟到编译期 |
| `list(APPEND CMAKE_PREFIX_PATH)` | 添加包搜索根 | 必须 APPEND | 覆盖系统路径 |
| `find_package(... CONFIG REQUIRED)` | 找 SDK 的 config 包 | 两个开关都必要 | 找不到时报错位置会靠后 |
| `add_executable` | 声明可执行目标 | 名字 + 源文件 | — |
| `target_link_libraries(... PRIVATE)` | 链接库 | 用导入目标名 | 缺头文件路径与 `.so` 路径 |
| `set_target_properties(... RPATH)` | 固化运行期搜索路径 | BUILD 与 INSTALL 都要 | 运行时报找不到 `.so` |
| `target_compile_options` | 告警级别 | `-Wall -Wextra -Wpedantic` | 不合规范的写法要到运行期才暴露 |

## 文档对照

| 主题 | 参考 |
| --- | --- |
| CMake 的 `find_package` 与 config 包 | [CMake 官方文档 · find_package](https://cmake.org/cmake/help/latest/command/find_package.html) |
| 导入目标（`MaaFramework::MaaFramework`） | [CMake 官方文档 · Imported Targets](https://cmake.org/cmake/help/latest/manual/cmake-buildsystem.7.html#imported-targets) |
| RPATH 机制 | [CMake 官方文档 · BUILD_RPATH](https://cmake.org/cmake/help/latest/prop_tgt/BUILD_RPATH.html) |
| 官方 sample 的写法 | `/opt/maafw/extract/sample/cpp/CMakeLists.txt` |
| MaaFramework 构建选项 | `[FW-4.1]` 构建指南 |
| ControlUnit 为什么是独立 `.so` | 本仓库 [`docs/02`](../docs/02-Wlroots输入链路解剖.md) 与 `[FW-4.2]` |

## 自测 5 题

1. `find_package(MaaFramework CONFIG REQUIRED)` 具体去哪个路径找文件？
2. 为什么 `list(APPEND CMAKE_PREFIX_PATH ...)` 不能写成 `set(...)`？
3. 程序编好了，直接运行报 `error while loading shared libraries`，三种解法分别是什么？哪个最省事？
4. 为什么 RPATH 要指向 `bin` 目录，而不是只链 `libMaaFramework.so`？
5. `target_link_libraries` 的 `PRIVATE` 与 `PUBLIC` 有什么区别？

<details>
<summary>答案</summary>

1. 找 `<CMAKE_PREFIX_PATH 的某一项>/share/cmake/MaaFramework/MaaFrameworkConfig.cmake`；本机是 `/opt/maafw/extract/share/cmake/MaaFramework/`。
2. `set` 会覆盖整个变量，把 CMake 默认搜索路径（`/usr` 等）冲掉，其他包就找不到了。
3. ① 设 RPATH（写进 ELF）② 每次带 `LD_LIBRARY_PATH` ③ 把 `.so` 装进 `/usr/local/lib` 并 `ldconfig`。最省事且不污染系统的是 RPATH。
4. 因为 Linux 控制器的 ControlUnit 是**独立 `.so`**，由框架运行期 `dlopen` 加载，所以整个 `bin` 目录都要在搜索路径里。
5. `PRIVATE` 只给自己用；`PUBLIC` 自己也用、且传染给链接本目标的其他目标；`INTERFACE` 自己不用、只给依赖者用。

</details>

## 实测补正：这条 `find_package` 路线在本机走不通

写完本文后实际编译，`find_package(MaaFramework CONFIG REQUIRED)` **在生成阶段失败**：

```text
There is a typo in the target name.
  A find_package call is missing for an IMPORTED target.
Call Stack:
  .../share/cmake/MaaFramework/MaaFrameworkConfig.cmake:27 (include)
```

原因不是写错目标名，而是 SDK 的导入目标声明了 link-dependent 依赖：

```cmake
IMPORTED_LINK_DEPENDENT_LIBRARIES_RELWITHDEBINFO
  "MaaFramework::MaaUtils;opencv_core;opencv_imgproc;opencv_imgcodecs;fastdeploy_ppocr;ONNXRuntime::ONNXRuntime"
```

而 release 包 `share/cmake/` 下**只有** `MaaFramework` 与 `MaaAgentServer` 两个 config，
`MaaUtils` / OpenCV / ONNXRuntime 的 config 都不在包里 → 这些 `ImportedTarget` 无法解析。

两条出路，我们选了后者：

| 路线 | 做法 | 代价 |
| --- | --- | --- |
| A. 用完整 install 树 | 自己 `cmake --install` 构建过的 MaaFramework（那样才有全部 config） | 要完整构建一遍，且和发布包版本可能不一致 |
| B. 直接链 `.so`（采用） | `target_include_directories` + `target_link_directories` + `target_link_libraries(... MaaFramework)` | 手动写三个路径，但只依赖 `DT_NEEDED` |

B 可行的依据：`libMaaFramework.so` 自己的 `DT_NEEDED` 已经记录了那些依赖库：

```text
libfastdeploy_ppocr.so  libonnxruntime.so.1  libMaaUtils.so
libopencv_world4.so.412  libc++.so.1  libc++abi.so.1 ...
```

实测 `LD_LIBRARY_PATH=/opt/maafw/extract/bin ldd libMaaFramework.so` → **0 个 not found**，
而 RPATH 又把 `bin` 固化进去了，所以可执行文件直接能跑。

**教训**：`find_package` 能省事，但只在「SDK 是完整安装树」时成立。
发布包（release tarball）是给最终用户运行用的，不一定带齐开发期依赖的 config。
遇到这类报错，先看包里到底有哪几个 `*Config.cmake`，别怀疑自己的 target 名。
