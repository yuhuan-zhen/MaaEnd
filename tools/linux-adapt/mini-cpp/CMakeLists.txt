cmake_minimum_required(VERSION 3.20)
project(maaend_linux_adapt_l0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# MaaFramework SDK 位置。默认用本机已解包的那份，可用 -DMAAFW_SDK_DIR=... 覆盖。
# SDK 目录结构：include/MaaFramework/*  +  bin/libMaaFramework.so  +  share/cmake/...
if(NOT DEFINED MAAFW_SDK_DIR)
    set(MAAFW_SDK_DIR "/opt/maafw/extract")
endif()

if(NOT EXISTS "${MAAFW_SDK_DIR}/include/MaaFramework/MaaAPI.h")
    message(FATAL_ERROR "找不到 MaaFramework SDK：${MAAFW_SDK_DIR}\n"
                        "请用 -DMAAFW_SDK_DIR=<包含 include 与 bin 的目录> 指定")
endif()

list(APPEND CMAKE_PREFIX_PATH "${MAAFW_SDK_DIR}")
find_package(MaaFramework CONFIG REQUIRED)

add_executable(l0_env l0_env.cpp)
target_link_libraries(l0_env PRIVATE MaaFramework::MaaFramework)

# 运行时库路径：Linux 控制器的 ControlUnit 是独立 .so，由框架在运行期 dlopen，
# 因此 bin 目录必须在动态链接器能搜到的地方（RPATH 或 LD_LIBRARY_PATH）。
set_target_properties(l0_env PROPERTIES
    BUILD_RPATH "${MAAFW_SDK_DIR}/bin"
    INSTALL_RPATH "${MAAFW_SDK_DIR}/bin")

target_compile_options(l0_env PRIVATE -Wall -Wextra -Wpedantic)
