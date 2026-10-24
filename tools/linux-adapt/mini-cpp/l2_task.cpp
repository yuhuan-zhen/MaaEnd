// L2 · Tasker + Resource：加载资源、绑定控制器、跑一个节点到 Succeeded
//
// 本层引入两个新句柄：MaaResource（资源）与 MaaTasker（执行器）。
// 与 L0/L1 的区别：L0/L1 只有 controller（截图 + 输入），L2 才有人「按 pipeline 干活」。

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "MaaFramework/MaaAPI.h"

namespace
{

constexpr const char* kDefaultSocketPath = "/run/user/0/wayland-1";
constexpr const char* kEntry = "L2Click";
constexpr const char* kNodeClick = "L2Click";
constexpr const char* kNodeDone = "L2Done";

void log_info(const char* fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    std::printf("[INFO] ");
    std::vprintf(fmt, args);
    std::printf("\n");
    va_end(args);
    std::fflush(stdout);
}

void log_error(const char* fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    std::printf("[ERR ] ");
    std::vprintf(fmt, args);
    std::printf("\n");
    va_end(args);
    std::fflush(stdout);
}

const char* status_name(MaaStatus status)
{
    switch (status) {
    case MaaStatus_Invalid:
        return "Invalid";
    case MaaStatus_Pending:
        return "Pending";
    case MaaStatus_Running:
        return "Running";
    case MaaStatus_Succeeded:
        return "Succeeded";
    case MaaStatus_Failed:
        return "Failed";
    default:
        return "Unknown";
    }
}

// 通用句柄守卫：C API 的句柄都是裸指针，用 RAII 统一销毁。
template <typename Handle, void (*Destroy)(Handle*)>
class ScopedHandle
{
public:
    explicit ScopedHandle(Handle* handle)
        : handle_(handle)
    {
    }

    ~ScopedHandle()
    {
        if (handle_ != nullptr) {
            Destroy(handle_);
        }
    }

    ScopedHandle(const ScopedHandle&) = delete;
    ScopedHandle& operator=(const ScopedHandle&) = delete;

    Handle* get() const { return handle_; }

    explicit operator bool() const { return handle_ != nullptr; }

private:
    Handle* handle_ = nullptr;
};

using ScopedController = ScopedHandle<MaaController, MaaControllerDestroy>;
using ScopedResource = ScopedHandle<MaaResource, MaaResourceDestroy>;
using ScopedTasker = ScopedHandle<MaaTasker, MaaTaskerDestroy>;
using ScopedString = ScopedHandle<MaaStringBuffer, MaaStringBufferDestroy>;
using ScopedStringList = ScopedHandle<MaaStringListBuffer, MaaStringListBufferDestroy>;

std::string build_config_json(const std::string& socket_path)
{
    return std::string("{\"screencap_method\":") + std::to_string(MaaLinuxScreencapMethod_Wlr) + ",\"input_method\":" + std::to_string(MaaLinuxInputMethod_Wlr)
           + ",\"wlr_socket_path\":\"" + socket_path + "\"" + ",\"use_win32_vk_code\":true}";
}

// 事件回调：MaaFramework 通过 sink 把节点级事件推给我们。
// 签名必须与 MaaEventCallback 完全一致（void* handle, message, details_json, trans_arg）。
void MAA_CALL event_sink(void* /*handle*/, const char* message, const char* /*details_json*/, void* trans_arg)
{
    auto* counter = static_cast<int*>(trans_arg);
    if (counter == nullptr) {
        return;
    }
    ++(*counter);
    log_info("event: %s", message);
}

// 节点级回调（context sink）：与 event_sink 同签名，只是注册入口不同。
void MAA_CALL context_event_sink(void* /*handle*/, const char* message, const char* /*details_json*/, void* trans_arg)
{
    auto* counter = static_cast<int*>(trans_arg);
    if (counter == nullptr) {
        return;
    }
    ++(*counter);
    log_info("ctx-event: %s", message);
}

int run(const std::string& socket_path, const std::string& resource_path)
{
    // ---------- 1. 控制器（与 L0 相同） ----------
    ScopedController controller(MaaLinuxControllerCreate(build_config_json(socket_path).c_str()));
    if (!controller) {
        log_error("MaaLinuxControllerCreate failed");
        return 1;
    }
    const MaaCtrlId conn_id = MaaControllerPostConnection(controller.get());
    if (conn_id == 0) {
        log_error("MaaControllerPostConnection rejected");
        return 1;
    }
    const MaaStatus conn_status = MaaControllerWait(controller.get(), conn_id);
    if (conn_status != MaaStatus_Succeeded || !MaaControllerConnected(controller.get())) {
        log_error("connect failed: %s", status_name(conn_status));
        return 1;
    }
    log_info("controller connected");

    // ---------- 2. 资源 ----------
    ScopedResource resource(MaaResourceCreate());
    if (!resource) {
        log_error("MaaResourceCreate failed");
        return 2;
    }

    // PostBundle 指向「包含 pipeline / image / model 的目录」，不是 pipeline 子目录
    const MaaResId res_id = MaaResourcePostBundle(resource.get(), resource_path.c_str());
    if (res_id == 0) {
        log_error("MaaResourcePostBundle rejected: %s", resource_path.c_str());
        return 2;
    }
    const MaaStatus res_status = MaaResourceWait(resource.get(), res_id);
    if (res_status != MaaStatus_Succeeded || !MaaResourceLoaded(resource.get())) {
        log_error("resource load failed: %s", status_name(res_status));
        return 2;
    }

    // 印出加载到的节点数：证明 pipeline JSON 真的被读进来了
    ScopedStringList node_list(MaaStringListBufferCreate());
    if (node_list && MaaResourceGetNodeList(resource.get(), node_list.get())) {
        log_info("resource nodes: %d", static_cast<int>(MaaStringListBufferSize(node_list.get())));
        for (MaaSize i = 0; i < MaaStringListBufferSize(node_list.get()); ++i) {
            const MaaStringBuffer* name = MaaStringListBufferAt(node_list.get(), i);
            if (name != nullptr) {
                log_info("  - %s", MaaStringBufferGet(name));
            }
        }
    }

    // ---------- 3. 执行器 ----------
    ScopedTasker tasker(MaaTaskerCreate());
    if (!tasker) {
        log_error("MaaTaskerCreate failed");
        return 3;
    }

    int event_count = 0;
    int context_event_count = 0;
    MaaTaskerAddSink(tasker.get(), &event_sink, &event_count);
    // 节点级事件走 context sink（任务级走上面的 sink），两者分开注册。
    MaaTaskerAddContextSink(tasker.get(), &context_event_sink, &context_event_count);

    if (!MaaTaskerBindResource(tasker.get(), resource.get())) {
        log_error("MaaTaskerBindResource failed");
        return 3;
    }
    if (!MaaTaskerBindController(tasker.get(), controller.get())) {
        log_error("MaaTaskerBindController failed");
        return 3;
    }
    if (!MaaTaskerInited(tasker.get())) {
        log_error("MaaTaskerInited == false（资源或控制器没就绪）");
        return 3;
    }
    log_info("tasker inited");

    // ---------- 4. 跑任务 ----------
    // pipeline_override 必须是合法 JSON 字符串，空串会被解析失败
    const MaaTaskId task_id = MaaTaskerPostTask(tasker.get(), kEntry, "{}");
    if (task_id == 0) {
        log_error("MaaTaskerPostTask rejected");
        return 4;
    }

    const MaaStatus final_status = MaaTaskerWait(tasker.get(), task_id);
    log_info("task %lld -> %s", static_cast<long long>(task_id), status_name(final_status));
    if (final_status != MaaStatus_Succeeded) {
        log_error("task failed");
        return 4;
    }

    // ---------- 5. 取回执行轨迹 ----------
    MaaNodeId node_ids[64] = {};
    MaaSize node_count = 64;
    MaaStatus detail_status = MaaStatus_Invalid;
    ScopedString entry_buf(MaaStringBufferCreate());

    if (!MaaTaskerGetTaskDetail(tasker.get(), task_id, entry_buf.get(), node_ids, &node_count, &detail_status)) {
        log_error("MaaTaskerGetTaskDetail failed");
        return 5;
    }
    log_info("executed nodes: %d (entry=%s)", static_cast<int>(node_count), MaaStringBufferGet(entry_buf.get()));

    int completed_count = 0;
    bool saw_click = false;
    bool saw_done = false;
    for (MaaSize i = 0; i < node_count; ++i) {
        ScopedString name(MaaStringBufferCreate());
        MaaRecoId reco_id = 0;
        MaaActId action_id = 0;
        MaaBool completed = 0;

        if (!MaaTaskerGetNodeDetail(tasker.get(), node_ids[i], name.get(), &reco_id, &action_id, &completed)) {
            log_error("  node[%d] detail unavailable", static_cast<int>(i));
            continue;
        }
        log_info(
            "  node[%d] %-10s reco=%-4lld act=%-4lld completed=%d",
            static_cast<int>(i),
            MaaStringBufferGet(name.get()),
            static_cast<long long>(reco_id),
            static_cast<long long>(action_id),
            static_cast<int>(completed));

        if (completed != 0) {
            ++completed_count;
        }
        if (std::strcmp(MaaStringBufferGet(name.get()), kNodeClick) == 0) {
            saw_click = true;
        }
        if (std::strcmp(MaaStringBufferGet(name.get()), kNodeDone) == 0) {
            saw_done = true;
        }
    }

    log_info("events received: %d, context events: %d", event_count, context_event_count);

    // ---------- 6. 判据 ----------
    if (node_count != 2 || completed_count != 2 || !saw_click || !saw_done) {
        log_error(
            "unexpected trace: nodes=%d completed=%d click=%d done=%d",
            static_cast<int>(node_count),
            completed_count,
            static_cast<int>(saw_click),
            static_cast<int>(saw_done));
        return 5;
    }

    log_info("L2 OK");
    return 0;
}

} // namespace

int main(int argc, char** argv)
{
    std::string socket_path = kDefaultSocketPath;
    std::string resource_path = "./l2-resource";

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_path = argv[++i];
        }
        else if (std::strcmp(argv[i], "--resource") == 0 && i + 1 < argc) {
            resource_path = argv[++i];
        }
    }

    log_info("MaaFramework %s", MaaVersion());
    log_info("socket=%s resource=%s", socket_path.c_str(), resource_path.c_str());

    return run(socket_path, resource_path);
}
