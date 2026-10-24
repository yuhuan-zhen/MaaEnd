// L0：环境与最小程序
//
// 目标：证明三件事
//   1. SDK 能链接（MaaVersion 打出版本号）
//   2. 能用 config_json 建出 Linux 控制器
//   3. 能连上合成器（PostConnection → Wait → Succeeded → Connected）
//
// 只读：不注入任何输入。全程只有 create / connect / query / destroy。

// =============================================================================
// 这份文件在干什么（小白先读这一段）
// =============================================================================
//
// 它是整个 C++ 路线的「点亮第一个灯泡」：不截图、不点击、不跑任务，
// 只验证「我的程序能不能跟 MaaFramework 说上话，并让它连上合成器」。
//
// 为什么先做这个而不是直接截图：
//   链接错了 / 头文件版本不对 / 运行期找不到 .so —— 这三个问题会在任何
//   真实功能里以「莫名其妙失败」的形式出现。先用一个 60 行的程序把它们暴露出来，
//   后面 L1~L5 的报错才有意义。
//
// 名词（第一次出现就解释）：
//   - handle（句柄）：C API 不把对象结构暴露给调用者，只给一个不透明指针。
//     你拿着它调函数，但看不见里面有什么。谁创建谁销毁，忘了就是泄漏。
//   - RAII：C++ 的「构造函数拿资源、析构函数放资源」写法。
//     ScopedController 一离开作用域就自动 Destroy，比手写 goto cleanup 安全。
//   - MaaCtrlId：一次「异步操作」的编号。Post* 立刻返回编号，Wait 用编号等结果。
//   - MaaStatus：状态整数。1000 Pending / 2000 Running / 3000 Succeeded / 4000 Failed。
//   - config_json：Linux 控制器的全部配置，用 JSON 字符串传进去（不是结构体）。
//   - RPATH：ELF 里记录「运行时去哪找 .so」的字段。控制器的 ControlUnit 是独立 .so，
//     由框架在运行期 dlopen，所以 bin 目录必须能被找到。
//
// 文档对照（完整链接见 PLAN.md 的「上游文档索引」）：
//   [FW-2.2] 集成接口一览 —— 本文件每个函数的签名与语义
//   [FW-2.4] 控制方式说明 —— screencap_method / input_method 的取值
//   [HDR]    MaaController.h / MaaUtility.h —— 权威声明
//
// =============================================================================

// MaaAPI.h 是总入口，它 include 了 MaaDef.h（枚举）、Global、Instance、Utility 四组头文件。
// 只引这一个就够，不需要逐个 include。
#include <MaaFramework/MaaAPI.h>

// C 头文件里的整数类型：MaaStatus / MaaBool / MaaCtrlId 的底层类型都来自 stdint。
#include <cstdint>
// printf / fprintf：独立小工具不引日志库，直接往标准输出/标准错误打。
#include <cstdio>
// std::string / std::to_string：拼日志与 JSON 用，省掉手写字符数组。
#include <string>

// 自己的命名空间。规范要求 namespace 用 lowercase（见 cpp-algo-style）。
namespace mini
{

// 截图方式的枚举值：1 = Wlr（走 zwlr-screencopy 协议）。
// 数字出处 [FW-2.4] 的 Linux Screencap 表；写错不会报错，只会静默换成别的方式。
constexpr int kScreencapMethodWlr = 1;

// 输入方式的枚举值：1 = Wlr（走 wlr virtual pointer 协议）。出处同上。
constexpr int kInputMethodWlr = 1;

// 嵌套 sway 的 socket 路径。
// 为什么是 wayland-1 而不是 wayland-0：wayland-0 被 WSLg 自己占用了。
// 常量命名规范：k 前缀 + PascalCase。
constexpr const char* kDefaultSocketPath = "/run/user/0/wayland-1";

// 两个极简日志函数。为什么不用 <MaaUtils/Logger.h>：
// 那是 cpp-algo 的公共库，本目录是独立 target，没链接 MaaUtils。
// 正式合并进 agent/cpp-algo 时应改成 LogInfo << VAR(x) 的写法（见 [ME-4]）。
void log_info(const std::string& message)
{
    // %s + c_str()：printf 不认识 std::string，只能用 C 字符串。
    std::printf("[INFO] %s\n", message.c_str());
}

void log_error(const std::string& message)
{
    // 错误走 stderr，方便脚本把正常输出和错误分开抓。
    std::fprintf(stderr, "[ERR ] %s\n", message.c_str());
}

// 控制器句柄的 RAII 包装。
// C API 的句柄都是裸指针，没有析构函数；包一层类之后，异常路径也不会泄漏。
class ScopedController
{
public:
    // explicit：禁止 MaaController* 隐式转换成 ScopedController，
    // 避免 foo(controller) 这种写法悄悄建出一个临时对象、出来就销毁。
    explicit ScopedController(MaaController* handle)
        : handle_(handle) // 成员变量命名：snake_case + 尾下划线
    {
    }

    // 析构：离开作用域时自动销毁。这就是 RAII 的全部魔法。
    ~ScopedController()
    {
        // 必须先判空：MaaLinuxControllerCreate 失败时返回 nullptr，
        // 把 nullptr 传给 Destroy 是未定义行为。
        if (handle_ != nullptr) {
            MaaControllerDestroy(handle_);
        }
    }

    // 禁止拷贝：两个对象持有同一个句柄会 double free。规范要求显式 delete。
    ScopedController(const ScopedController&) = delete;
    ScopedController& operator=(const ScopedController&) = delete;

    // 取出裸句柄，供 C API 调用（它们只认 MaaController*）。
    MaaController* get() const { return handle_; }

    // explicit operator bool：让 `if (!controller)` 这种写法合法，
    // 语义是「句柄是否有效」。explicit 防止它被隐式转成 int 参与意外运算。
    explicit operator bool() const { return handle_ != nullptr; }

private:
    // 句柄默认空，成员初始化列表里赋值。
    MaaController* handle_ = nullptr;
};

// 把配置拼成 JSON 字符串。C API 不收结构体，只收 JSON 文本。
// 为什么不引 meojson：独立 target 不想多一个依赖；这里只有 4 个字段，
// 且 socket 路径里不会出现需要转义的字符。字段多起来再用库。
std::string build_config_json(const std::string& socket_path)
{
    std::string json;
    json += "{";
    // std::to_string 把 int 转成字符串，避免手写 "1" 这种魔法字符串。
    json += "\"screencap_method\": " + std::to_string(kScreencapMethodWlr) + ",";
    json += "\"input_method\": " + std::to_string(kInputMethodWlr) + ",";
    // socket 路径用引号包住，拼进 JSON 字符串。
    json += "\"wlr_socket_path\": \"" + socket_path + "\",";
    // use_win32_vk_code：true 表示上层传进来的键码按 Win32 VK 解释（27 = Esc）。
    // 这个字段不写也不会报错，但默认 false 会导致按键全部错位（见 [FW-2.4]）。
    json += "\"use_win32_vk_code\": true";
    json += "}";
    return json;
}

// 提交连接任务并等待结果。
// 注意 MaaFramework 的异步约定：Post* 只是「提交」，返回一个 id；
// Wait 才真正阻塞到结束；Succeeded 才是「做成了」。
bool connect_controller(MaaController* controller)
{
    // 提交连接；返回的 id 用于后面的 Wait。
    const MaaCtrlId job_id = MaaControllerPostConnection(controller);
    // id 为 0 表示提交失败（参数非法或控制器已销毁），不必再等。
    if (job_id == 0) {
        log_error("MaaControllerPostConnection returned invalid id");
        return false;
    }

    // Wait 返回最终状态（MaaStatus 是 int32_t）。
    const MaaStatus status = MaaControllerWait(controller, job_id);
    // 只要不是 Succeeded 就算失败：可能是 Failed(4000)，也可能是超时/待定。
    if (status != MaaStatus_Succeeded) {
        // to_string 让日志能直接看出是哪一种状态。
        log_error("connect failed, status = " + std::to_string(status));
        return false;
    }

    return true;
}

} // namespace mini

// 程序入口。argc/argv 允许从命令行传 socket 路径，方便换合成器实例。
int main(int argc, char** argv)
{
    // 有参数就用参数，否则用默认路径。三元表达式，注意两边类型一致（都是 std::string）。
    const std::string socket_path = (argc > 1) ? argv[1] : mini::kDefaultSocketPath;

    // MaaVersion() 返回 const char*，可能为 null（理论上不会），保险起见判一下。
    // 这一行能打出来，就说明「头文件版本对」+「动态库链接成功」两件事都成立。
    const char* version = MaaVersion();
    mini::log_info(std::string("MaaFramework version: ") + (version != nullptr ? version : "(null)"));

    // 拼配置并打出来：出问题时第一眼看的就是这里，确认 socket 路径没写错。
    const std::string config = mini::build_config_json(socket_path);
    mini::log_info("config: " + config);

    // 创建控制器。这一步只建对象，还没连；失败返回 nullptr。
    // c_str() 把 std::string 转成 C API 需要的 const char*。
    mini::ScopedController controller(MaaLinuxControllerCreate(config.c_str()));
    // operator bool 生效：句柄无效就进这个分支。
    if (!controller) {
        mini::log_error("MaaLinuxControllerCreate returned nullptr");
        // 返回 1 表示「环境/参数错误」，与下面「连不上」用不同退出码区分。
        return 1;
    }
    mini::log_info("controller created");

    // 连接；失败直接退出（此时 ScopedController 会自动销毁句柄）。
    if (!mini::connect_controller(controller.get())) {
        return 1;
    }

    // MaaControllerConnected 是「同步查询当前连接状态」，与前面 Wait 的结果应一致。
    // 它是 MaaBool（uint8），所以和 0 比较，不能直接当 bool 用（虽然通常也行）。
    const bool connected = MaaControllerConnected(controller.get()) != 0;
    mini::log_info(std::string("connected = ") + (connected ? "true" : "false"));

    // GetResolution 返回的是「最近一次成功截图的尺寸」；本程序没截图，缓存为 0，故预期 false。
    // 这里只记录，不作为失败条件——把它当失败会让你误判环境。
    // 这里只记录、不作为失败条件——把它当失败会让你误以为环境有问题。
    int32_t width = 0;
    int32_t height = 0;
    // 两个 int32_t* 是出参；返回 MaaBool 表示「这个 API 调用本身是否成功」。
    if (MaaControllerGetResolution(controller.get(), &width, &height)) {
        mini::log_info("resolution = " + std::to_string(width) + "x" + std::to_string(height));
    }
    else {
        mini::log_info("resolution unavailable");
    }

    // 退出码：0 = 全部成功；2 = 建好了但没连上。1 已在上面表示参数/环境错误。
    return connected ? 0 : 2;
}
