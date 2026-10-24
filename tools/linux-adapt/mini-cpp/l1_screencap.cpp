// L1：截图
//
// 目标：证明四件事
//   1. 能从 Linux 控制器抓到一帧，尺寸与通道数正确（预期 1280×720、3 通道、uint8）
//   2. 通道序是 BGR 而不是 RGB —— 用合成器背景色当判据（B > G > R 即 BGR）
//   3. `MaaControllerGetResolution` 在截过一帧之后有值（L0 里它是 false，因为没截图）
//   4. 单帧耗时量级（Wlr 实测中位 16.2 ms，见 docs/05）
//
// 只读：抓帧 + 存盘，不注入任何输入。

#include <MaaFramework/MaaAPI.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace mini
{

// 截图与输入方式的枚举值，见 MaaDef.h 的 MaaLinuxScreencapMethod / MaaLinuxInputMethod。
constexpr int kScreencapMethodWlr = 1;
constexpr int kInputMethodWlr = 1;

// 嵌套 sway 的 socket。wayland-0 被 WSLg 占用，所以嵌套实例是 wayland-1。
constexpr const char* kDefaultSocketPath = "/run/user/0/wayland-1";

// 一帧的默认抓取数量（用于计时统计）。
constexpr int kDefaultFrames = 20;

void log_info(const std::string& message)
{
    std::printf("[INFO] %s\n", message.c_str());
}

void log_error(const std::string& message)
{
    std::fprintf(stderr, "[ERR ] %s\n", message.c_str());
}

// 控制器句柄的 RAII 包装：离开作用域自动 MaaControllerDestroy。
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

// 图像缓冲区的 RAII 包装：离开作用域自动 MaaImageBufferDestroy。
class ScopedImageBuffer
{
public:
    ScopedImageBuffer()
        : buffer_(MaaImageBufferCreate())
    {
    }

    ~ScopedImageBuffer()
    {
        if (buffer_ != nullptr) {
            MaaImageBufferDestroy(buffer_);
        }
    }

    ScopedImageBuffer(const ScopedImageBuffer&) = delete;
    ScopedImageBuffer& operator=(const ScopedImageBuffer&) = delete;

    MaaImageBuffer* get() const { return buffer_; }

    explicit operator bool() const { return buffer_ != nullptr; }

private:
    MaaImageBuffer* buffer_ = nullptr;
};

// 一帧的「视图」：只记录指针与形状，不持有像素。
//
// 关键语义（对应 MaaEnd 的 to_mat）：这是**视图**，不是拷贝。
// data 指向 MaaImageBuffer 内部的像素内存，buffer 一销毁它就悬空。
// 所以：要么在 buffer 存活期间用完，要么自己 memcpy 出去。
struct ImageView
{
    const uint8_t* data = nullptr;
    int width = 0;
    int height = 0;
    int channels = 0;
    int type = 0;

    bool empty() const { return data == nullptr || width <= 0 || height <= 0; }
};

ImageView to_view(const MaaImageBuffer* buffer)
{
    ImageView view;
    if (buffer == nullptr) {
        return view;
    }

    view.data = static_cast<const uint8_t*>(MaaImageBufferGetRawData(buffer));
    view.width = MaaImageBufferWidth(buffer);
    view.height = MaaImageBufferHeight(buffer);
    view.channels = MaaImageBufferChannels(buffer);
    view.type = MaaImageBufferType(buffer);
    return view;
}

// 某个通道的均值。void* 转成字节指针后按 channels 步长跳。
double channel_mean(const ImageView& view, int channel)
{
    if (view.empty() || channel < 0 || channel >= view.channels) {
        return 0.0;
    }

    const size_t pixel_count = static_cast<size_t>(view.width) * static_cast<size_t>(view.height);
    if (pixel_count == 0) {
        return 0.0;
    }

    uint64_t sum = 0;
    for (size_t i = 0; i < pixel_count; ++i) {
        sum += view.data[i * static_cast<size_t>(view.channels) + static_cast<size_t>(channel)];
    }
    return static_cast<double>(sum) / static_cast<double>(pixel_count);
}

// 把缓冲区的 PNG 编码直接写盘。MaaFramework 内部做编码，所以不需要 OpenCV。
bool save_png(const MaaImageBuffer* buffer, const std::string& path)
{
    const uint8_t* encoded = MaaImageBufferGetEncoded(buffer);
    const MaaSize size = MaaImageBufferGetEncodedSize(buffer);
    if (encoded == nullptr || size == 0) {
        log_error("MaaImageBufferGetEncoded returned empty");
        return false;
    }

    std::FILE* file = std::fopen(path.c_str(), "wb");
    if (file == nullptr) {
        log_error("cannot open output file: " + path);
        return false;
    }

    const size_t written = std::fwrite(encoded, 1, static_cast<size_t>(size), file);
    std::fclose(file);

    if (written != static_cast<size_t>(size)) {
        log_error("short write: " + std::to_string(written) + "/" + std::to_string(size));
        return false;
    }

    log_info("saved " + path + " (" + std::to_string(size) + " bytes, PNG)");
    return true;
}

std::string build_config_json(const std::string& socket_path)
{
    std::string json = "{";
    json += "\"screencap_method\": " + std::to_string(kScreencapMethodWlr) + ",";
    json += "\"input_method\": " + std::to_string(kInputMethodWlr) + ",";
    json += "\"wlr_socket_path\": \"" + socket_path + "\",";
    json += "\"use_win32_vk_code\": true";
    json += "}";
    return json;
}

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

// 抓一帧：提交任务 → 等待 → 取缓存图。返回耗时（毫秒），失败返回 -1。
double grab_once(MaaController* controller, MaaImageBuffer* buffer)
{
    const auto begin = std::chrono::steady_clock::now();

    const MaaCtrlId job_id = MaaControllerPostScreencap(controller);
    if (job_id == 0) {
        log_error("MaaControllerPostScreencap returned invalid id");
        return -1.0;
    }

    const MaaStatus status = MaaControllerWait(controller, job_id);
    if (status != MaaStatus_Succeeded) {
        log_error("screencap failed, status = " + std::to_string(status));
        return -1.0;
    }

    if (!MaaControllerCachedImage(controller, buffer)) {
        log_error("MaaControllerCachedImage returned false");
        return -1.0;
    }

    const auto end = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(end - begin).count();
}

double percentile(std::vector<double> values, double ratio)
{
    if (values.empty()) {
        return 0.0;
    }

    std::sort(values.begin(), values.end());
    const size_t index = static_cast<size_t>(ratio * static_cast<double>(values.size() - 1));
    return values[std::min(index, values.size() - 1)];
}

struct Options
{
    std::string socket_path = kDefaultSocketPath;
    std::string out_path = "frame.png";
    int frames = kDefaultFrames;
};

Options parse_args(int argc, char** argv)
{
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--out" && i + 1 < argc) {
            options.out_path = argv[++i];
        }
        else if (arg == "--frames" && i + 1 < argc) {
            options.frames = std::atoi(argv[++i]);
        }
        else {
            options.socket_path = arg;
        }
    }
    return options;
}

} // namespace mini

int main(int argc, char** argv)
{
    const mini::Options options = mini::parse_args(argc, argv);

    mini::log_info(std::string("MaaFramework version: ") + MaaVersion());

    const std::string config = mini::build_config_json(options.socket_path);
    mini::ScopedController controller(MaaLinuxControllerCreate(config.c_str()));
    if (!controller) {
        mini::log_error("MaaLinuxControllerCreate returned nullptr");
        return 1;
    }

    if (!mini::connect_controller(controller.get())) {
        return 1;
    }
    mini::log_info("connected = true");

    mini::ScopedImageBuffer image;
    if (!image) {
        mini::log_error("MaaImageBufferCreate returned nullptr");
        return 1;
    }

    // 第一帧：尺寸、通道、通道均值、落盘。
    const double first_ms = mini::grab_once(controller.get(), image.get());
    if (first_ms < 0.0) {
        return 1;
    }

    const mini::ImageView view = mini::to_view(image.get());
    mini::log_info(
        "frame = " + std::to_string(view.width) + "x" + std::to_string(view.height) + ", channels = " + std::to_string(view.channels)
        + ", type = " + std::to_string(view.type) + ", first_frame = " + std::to_string(first_ms) + " ms");

    // 通道均值。合成器背景是 #1b2b34（R=27 G=43 B=52），若按 BGR 读应得 B>G>R。
    const double mean_b = mini::channel_mean(view, 0);
    const double mean_g = mini::channel_mean(view, 1);
    const double mean_r = mini::channel_mean(view, 2);
    mini::log_info("channel mean BGR = [" + std::to_string(mean_b) + ", " + std::to_string(mean_g) + ", " + std::to_string(mean_r) + "]");

    if (!mini::save_png(image.get(), options.out_path)) {
        return 1;
    }

    // 截图之后再看分辨率：L0 里没截图所以是 false，现在应该给真值。
    int32_t raw_width = 0;
    int32_t raw_height = 0;
    if (MaaControllerGetResolution(controller.get(), &raw_width, &raw_height)) {
        mini::log_info("resolution = " + std::to_string(raw_width) + "x" + std::to_string(raw_height));
    }
    else {
        mini::log_info("resolution unavailable (unexpected after screencap)");
    }

    // 多帧计时。
    std::vector<double> samples;
    samples.reserve(static_cast<size_t>(options.frames));
    for (int i = 0; i < options.frames; ++i) {
        const double cost_ms = mini::grab_once(controller.get(), image.get());
        if (cost_ms < 0.0) {
            return 1;
        }
        samples.push_back(cost_ms);
    }

    if (!samples.empty()) {
        const auto [min_it, max_it] = std::minmax_element(samples.begin(), samples.end());
        mini::log_info(
            "screencap x" + std::to_string(samples.size()) + " ms: min = " + std::to_string(*min_it)
            + ", median = " + std::to_string(mini::percentile(samples, 0.5)) + ", p95 = " + std::to_string(mini::percentile(samples, 0.95))
            + ", max = " + std::to_string(*max_it));
    }

    return 0;
}
