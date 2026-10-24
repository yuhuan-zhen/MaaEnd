// L0：环境与最小程序
//
// 目标：证明三件事
//   1. SDK 能链接（MaaVersion 打出版本号）
//   2. 能用 config_json 建出 Linux 控制器
//   3. 能连上合成器（PostConnection → Wait → Succeeded → Connected）
//
// 只读：不注入任何输入。全程只有 create / connect / query / destroy。

#include <MaaFramework/MaaAPI.h>

#include <cstdint>
#include <cstdio>
#include <string>

namespace mini
{

// 截图与输入方式的枚举值，见 MaaDef.h 的 MaaLinuxScreencapMethod / MaaLinuxInputMethod
constexpr int kScreencapMethodWlr = 1;
constexpr int kInputMethodWlr = 1;

// 嵌套 sway 的 socket。wayland-0 被 WSLg 占用，所以是 wayland-1。
constexpr const char* kDefaultSocketPath = "/run/user/0/wayland-1";

void log_info(const std::string& message)
{
    std::printf("[INFO] %s\n", message.c_str());
}

void log_error(const std::string& message)
{
    std::fprintf(stderr, "[ERR ] %s\n", message.c_str());
}

// 控制器句柄的 RAII 包装：离开作用域自动 MaaControllerDestroy。
// C API 的 handle 全是不透明指针，谁创建谁销毁，忘掉销毁就是泄漏。
class ScopedController
{
public:
    explicit ScopedController(MaaController* handle)
        : handle_(handle)
    {
    }

    ~ScopedController()
    {
        if (handle_ != nullptr) {
            MaaControllerDestroy(handle_);
        }
    }

    ScopedController(const ScopedController&) = delete;
    ScopedController& operator=(const ScopedController&) = delete;

    MaaController* get() const { return handle_; }

    explicit operator bool() const { return handle_ != nullptr; }

private:
    MaaController* handle_ = nullptr;
};

// 拼控制器配置 JSON。独立小工具不引 meojson，手拼即可；路径里没有需要转义的字符。
std::string build_config_json(const std::string& socket_path)
{
    std::string json;
    json += "{";
    json += "\"screencap_method\": " + std::to_string(kScreencapMethodWlr) + ",";
    json += "\"input_method\": " + std::to_string(kInputMethodWlr) + ",";
    json += "\"wlr_socket_path\": \"" + socket_path + "\",";
    json += "\"use_win32_vk_code\": true";
    json += "}";
    return json;
}

// 提交连接任务并等待结果。返回是否连接成功。
bool connect_controller(MaaController* controller)
{
    const MaaCtrlId job_id = MaaControllerPostConnection(controller);
    if (job_id == 0) {
        log_error("MaaControllerPostConnection returned invalid id");
        return false;
    }

    const MaaStatus status = MaaControllerWait(controller, job_id);
    if (status != MaaStatus_Succeeded) {
        log_error("connect failed, status = " + std::to_string(status));
        return false;
    }

    return true;
}

} // namespace mini

int main(int argc, char** argv)
{
    const std::string socket_path = (argc > 1) ? argv[1] : mini::kDefaultSocketPath;

    const char* version = MaaVersion();
    mini::log_info(std::string("MaaFramework version: ") + (version != nullptr ? version : "(null)"));

    const std::string config = mini::build_config_json(socket_path);
    mini::log_info("config: " + config);

    mini::ScopedController controller(MaaLinuxControllerCreate(config.c_str()));
    if (!controller) {
        mini::log_error("MaaLinuxControllerCreate returned nullptr");
        return 1;
    }
    mini::log_info("controller created");

    if (!mini::connect_controller(controller.get())) {
        return 1;
    }

    const bool connected = MaaControllerConnected(controller.get()) != 0;
    mini::log_info(std::string("connected = ") + (connected ? "true" : "false"));

    // GetResolution 返回的是「最近一次成功截图的尺寸」；本程序没截图，缓存为 0，故预期 false。
    // 这里只记录，不作为失败条件——把它当失败会让你误判环境。
    int32_t width = 0;
    int32_t height = 0;
    if (MaaControllerGetResolution(controller.get(), &width, &height)) {
        mini::log_info("resolution = " + std::to_string(width) + "x" + std::to_string(height));
    }
    else {
        mini::log_info("resolution unavailable");
    }

    return connected ? 0 : 2;
}
