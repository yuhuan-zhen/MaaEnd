cmake_minimum_required(VERSION 3.20)
project(maaend_linux_adapt LANGUAGES CXX)

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

# 直接链 .so，不走 find_package。
# 原因：release 包只带 MaaFramework / MaaAgentServer 两个 CMake config，
# 而 MaaFramework 的导入目标把 MaaUtils / OpenCV / ONNXRuntime 声明为
# link-dependent 依赖，它们的 config 不在包里 → CMake 生成阶段直接报错。
# 直接链 .so 不需要那些 config：libMaaFramework.so 自身的 DT_NEEDED
# 已记录 opencv_world / onnxruntime / MaaUtils，运行时由 RPATH 解析。
# 两个可执行目标共用同一套配置：L0 验环境，L1 验截图。
# 用函数避免复制三遍路径设置。
function(maaend_add_tool target source)
    add_executable(${target} ${source})
    target_include_directories(${target} PRIVATE "${MAAFW_SDK_DIR}/include")
    target_link_directories(${target} PRIVATE "${MAAFW_SDK_DIR}/bin")
    target_link_libraries(${target} PRIVATE MaaFramework)
    set_target_properties(${target} PROPERTIES
        BUILD_RPATH "${MAAFW_SDK_DIR}/bin"
        INSTALL_RPATH "${MAAFW_SDK_DIR}/bin")
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
endfunction()

maaend_add_tool(l0_env l0_env.cpp)
maaend_add_tool(l1_screencap l1_screencap.cpp)
