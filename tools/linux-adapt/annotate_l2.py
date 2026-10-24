#!/usr/bin/env python3
"""为 l2_task.cpp 生成「逐行注释版」。

做法：按子串匹配定位代码行，只在行尾追加 `// 说明` 或在其上方插入 `// 说明`，
**不修改任何代码行本身**。因此对两个文件做预处理后必须逐字节相同（脚本自带校验）。

用法：
    python3 annotate_l2.py            # 生成并在原地校验 md5
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "mini-cpp" / "l2_task.cpp"
DST = HERE / "mini-cpp" / "l2_task_annotated.cpp"

# 行尾注释：(代码子串, 注释)
INLINE: list[tuple[str, str]] = [
    ('#include "MaaFramework/MaaAPI.h"', "唯一的公开总头，实例/工具/全局都在里面"),
    ("constexpr int kWlrMethod = 1;", "MaaLinuxScreencapMethod_WlrScreencap / Input_WlrInput 都是 1"),
    ("constexpr const char* kEntry =", "任务入口节点名，必须存在于资源里"),
    ("void log_info(const char* fmt, ...)", "SDK 不带 MaaUtils，独立宿主只能自己打日志"),
    ("    va_list args;", "C 风格可变参：先 va_start，再 vprintf，最后 va_end"),
    ("const char* status_name(MaaStatus status)", "把枚举翻译成可读串，日志里比对退出码更快"),
    ("    case MaaStatus_Succeeded:", "3000，任务成功"),
    ("template <typename Handle, void (*Destroy)(Handle*)>", "把销毁函数作为模板参数，一个模板覆盖五种句柄"),
    ("    explicit ScopedHandle(Handle* handle)", "explicit：禁止裸指针隐式转换成守卫对象"),
    ("    ~ScopedHandle()", "析构即销毁；这是 RAII 的全部机制"),
    ("    ScopedHandle(const ScopedHandle&) = delete;", "禁拷贝：两个对象持有同一句柄会 double free"),
    ("    Handle* get() const { return handle_; }", "C API 只认裸指针，需要一个取出口"),
    ("using ScopedController = ScopedHandle<MaaController, MaaControllerDestroy>;", "每种句柄一行别名，读代码不用记模板参数"),
    ("std::string build_config_json(const std::string& socket_path)", "config_json 是字符串而非结构体：加字段不破坏 ABI"),
    ('    return std::string("{\\"screencap_method\\":")', "只拼必填三项 + 一个显式开关"),
    ("void MAA_CALL event_sink(", "签名必须与 MaaEventCallback 完全一致，否则注册失败"),
    ("    ++(*counter);", "trans_arg 就是调用方传进来的指针，C 回调靠它回传状态"),
    ("void MAA_CALL context_event_sink(", "节点级事件走 context sink，与任务级 sink 分开注册"),
    ("    ScopedController controller(MaaLinuxControllerCreate(", "创建 Linux 控制器：截图 + 输入"),
    ("    const MaaCtrlId conn_id = MaaControllerPostConnection(", "post 只是提交，返回 0 表示提交失败"),
    ("    const MaaStatus conn_status = MaaControllerWait(", "wait 才真正阻塞等结果"),
    ("    ScopedResource resource(MaaResourceCreate());", "资源 = pipeline JSON + 模板图 + 模型"),
    ("    const MaaResId res_id = MaaResourcePostBundle(resource.get(), resource_path.c_str());", "PostBundle 收的是资源根目录"),
    ("    const MaaStatus res_status = MaaResourceWait(resource.get(), res_id);", "加载是异步的，必须 wait"),
    ("    ScopedStringList node_list(MaaStringListBufferCreate());", "列表缓冲区：用来取回节点名"),
    ('        log_info("resource nodes: %d"', "打印节点数即可证明 JSON 被解析"),
    ("    ScopedTasker tasker(MaaTaskerCreate());", "执行器：按 pipeline 干活的那一层"),
    ("    MaaTaskerAddSink(tasker.get(), &event_sink, &event_count);", "任务级事件（Tasker.Task.*）"),
    ("    MaaTaskerAddContextSink(tasker.get(), &context_event_sink, &context_event_count);", "节点级事件（Node.*）只走这里"),
    ("    if (!MaaTaskerBindResource(tasker.get(), resource.get())) {", "绑资源：先绑才能 inited"),
    ("    if (!MaaTaskerBindController(tasker.get(), controller.get())) {", "绑控制器：截图与输入都靠它"),
    ("    if (!MaaTaskerInited(tasker.get())) {", "两者都就绪才为真，是跑任务前的最后一道检查"),
    ('    const MaaTaskId task_id = MaaTaskerPostTask(tasker.get(), kEntry, "{}");', "override 必须是合法 JSON，空串会解析失败"),
    ("    const MaaStatus final_status = MaaTaskerWait(tasker.get(), task_id);", "阻塞到任务结束"),
    ("    MaaNodeId node_ids[64] = {};", "出参数组由调用方提供，容量用满前需自行保证"),
    ("    MaaSize node_count = 64;", "in&out：进是容量，出是实际条数"),
    ("    if (!MaaTaskerGetTaskDetail(", "取回「这次任务执行过哪些节点」"),
    ("        if (!MaaTaskerGetNodeDetail(", "逐节点查名字 / 识别 id / 动作 id / 是否完成"),
    ("        if (completed != 0) {", "completed 是 MaaBool，非 0 即成功"),
    ("    if (node_count != 2 || completed_count != 2", "判据：两个节点都执行且都完成"),
    ('    log_info("L2 OK");', "全部判据通过才打这行，脚本据此判定"),
    ("    for (int i = 1; i < argc; ++i) {", "只认 --socket / --resource，保持最小"),
]

# 行前注释：(代码子串, 注释)
ABOVE: list[tuple[str, str]] = [
    ("// 本层引入两个新句柄", ""),  # 占位，避免空列表
    ("namespace\n", ""),
    ("constexpr int kWlrMethod", "四个常量：方法枚举、默认 socket、入口节点名、两个节点名"),
    ("void log_info", "两个日志函数：一个走 stdout 前缀 INFO，一个前缀 ERR"),
    ("const char* status_name(", "MaaStatus 是 int32_t，只有五个取值"),
    ("template <typename Handle", "句柄守卫：把「析构即销毁」抽成模板，五种句柄共用"),
    ("std::string build_config_json(", "拼 controller 的 config_json"),
    ("void MAA_CALL event_sink(", "任务级事件回调"),
    ("void MAA_CALL context_event_sink(", "节点级事件回调"),
    ("int run(const std::string& socket_path", "主流程分六段：控制器 / 资源 / 执行器 / 跑任务 / 取轨迹 / 判据"),
    ("    // ---------- 2. 资源 ----------", ""),
    ("    // ---------- 3. 执行器 ----------", ""),
    ("    // ---------- 4. 跑任务 ----------", ""),
    ("    // ---------- 5. 取回执行轨迹 ----------", ""),
    ("    // ---------- 6. 判据 ----------", ""),
    ("int main(int argc, char** argv)", "入口：解析两个参数，打印版本，交给 run()"),
]


def md5_preprocessed(path: Path) -> str:
    """预处理后取 md5：注释被预处理器抹掉，剩下相同才算「只加了注释」。"""
    result = subprocess.run(
        ["g++", "-std=c++20", "-E", "-P", "-I", "/opt/maafw/extract/include", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"预处理失败：{path}\n{result.stderr[:800]}")
    return hashlib.md5(result.stdout.encode()).hexdigest()


def main() -> int:
    lines = SRC.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    inline_done: set[str] = set()
    above_done: set[str] = set()

    for line in lines:
        # 行前注释：只对非空行生效，避免插到空行前（看不出归属）
        if line.strip():
            for needle, comment in ABOVE:
                if comment and needle not in above_done and needle in line:
                    out.append(f"// {comment}")
                    above_done.add(needle)
                    break

        appended = line
        for needle, comment in INLINE:
            if needle in inline_done or needle not in line:
                continue
            # 已有行尾注释就不覆盖，避免出现两条注释挤在一起
            appended = f"{line}  // {comment}"
            inline_done.add(needle)
            break
        out.append(appended)

    DST.write_text("\n".join(out) + "\n", encoding="utf-8")

    a = md5_preprocessed(SRC)
    b = md5_preprocessed(DST)
    print(f"原文预处理 md5   : {a}")
    print(f"注释版预处理 md5 : {b}")
    if a != b:
        print("MISMATCH：注释版改动了代码语义")
        return 1
    print("MATCH：两文件预处理后完全一致（只差注释）")
    print(f"行数：{len(lines)} → {len(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
