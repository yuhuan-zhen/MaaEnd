// L1：截图
//
// 目标：证明四件事
//   1. 能从 Linux 控制器抓到一帧，尺寸与通道数正确（预期 1280×720、3 通道、uint8）
//   2. 通道序是 BGR 而不是 RGB —— 用合成器背景色当判据（B > G > R 即 BGR）
//   3. `MaaControllerGetResolution` 在截过一帧之后有值（L0 里它是 false，因为没截图）
//   4. 单帧耗时量级（Wlr 实测中位 16.2 ms，见 docs/05）
//
// 只读：抓帧 + 存盘，不注入任何输入。

// 唯一的框架头。MaaAPI.h 汇总了全部 C API（Instance/ 下 7 个 + Utility/ 下若干），
// 所以 L1 只需要这一行 include，不必逐个包含 MaaController.h / MaaBuffer.h。
#include <MaaFramework/MaaAPI.h>

// 标准库：std::minmax_element（L334）、std::sort（L235）、std::min（L237）。
#include <algorithm>
// std::chrono：计时用 steady_clock，不受系统时间调整影响。
#include <chrono>
// std::uint8_t / uint64_t：像素是 uint8，累加用 uint64 防溢出。
#include <cstdint>
// std::printf / std::fopen / std::fwrite：本程序不引入框架日志，用 C 标准 IO。
#include <cstdio>
// std::string：所有日志与路径。
#include <string>
// std::vector：存多帧耗时样本。
#include <vector>

// 命名空间 mini：内部工具全部收进来，不污染全局。
namespace mini
{

// 截图与输入方式的枚举值，见 MaaDef.h 的 MaaLinuxScreencapMethod / MaaLinuxInputMethod。
// Wlr 截图方式的枚举值（MaaDef.h：None=0, Wlr=1, ExtImage=2, PipeWire=4）。
constexpr int kScreencapMethodWlr = 1;
// Wlr 输入方式的枚举值（None=0, Wlr=1, UInput=2, Libei=4）。L1 只抓帧，但 config 要求两项都填。
constexpr int kInputMethodWlr = 1;

// 嵌套 sway 的 socket。wayland-0 被 WSLg 占用，所以嵌套实例是 wayland-1。
// 默认 socket。嵌套 sway 会占 wayland-1，因为 wayland-0 已被 WSLg 自己的合成器占用。
constexpr const char* kDefaultSocketPath = "/run/user/0/wayland-1";

// 一帧的默认抓取数量（用于计时统计）。
// 默认抓 20 帧做统计：够算 median/p95，又不至于让脚本跑太久。
constexpr int kDefaultFrames = 20;

// 日志函数：stdout 打正常信息，方便被 tee 存档。
void log_info(const std::string& message)
{
    std::printf("[INFO] %s\n", message.c_str());
}

// 错误走 stderr：这样 `2>/dev/null` 能把正常输出与报错分开。
void log_error(const std::string& message)
{
    std::fprintf(stderr, "[ERR ] %s\n", message.c_str());
}

// 控制器句柄的 RAII 包装：离开作用域自动 MaaControllerDestroy。
// 控制器句柄的 RAII 包装。
// 为什么必须包：C API 的句柄是不透明指针，忘掉 Destroy 就是泄漏；
// 上游自己在 ControlUnit.cpp:365 用 shared_ptr(handle, destroy_func) 做同一件事。
class ScopedController
{
public:
    // explicit：禁止 MaaController* 隐式转成 ScopedController，避免临时对象出来就析构。
    explicit ScopedController(MaaController* handle)
        : handle_(handle)
    {
    }

    // 析构里判空是防御性写法（上游 MaaControllerDestroy 自己判空，空句柄只打一行 LogError）。
    ~ScopedController()
    {
        if (handle_ != nullptr) {
            MaaControllerDestroy(handle_);
        }
    }

    // 禁拷贝：两个对象持同一句柄会 double free。删了拷贝，移动也不会被隐式生成。
    ScopedController(const ScopedController&) = delete;
    ScopedController& operator=(const ScopedController&) = delete;

    // 交出裸句柄，供 C API 调用。
    MaaController* get() const { return handle_; }

    // explicit operator bool：让 `if (!controller)` 合法，且不会被隐式转成 int。
    explicit operator bool() const { return handle_ != nullptr; }

private:
    // 成员默认空，构造时赋值。
    MaaController* handle_ = nullptr;
};

// 图像缓冲区的 RAII 包装：离开作用域自动 MaaImageBufferDestroy。
// 图像缓冲区也要 RAII：MaaImageBuffer 是框架内部分配的内存，必须 Destroy。
class ScopedImageBuffer
{
public:
    // MaaImageBufferCreate 不需要参数；空缓冲也能创建，抓帧后才有内容。
    ScopedImageBuffer()
        : buffer_(MaaImageBufferCreate())
    {
    }

    // 析构销毁缓冲区。注意：销毁后所有 ImageView 立刻悬空。
    ~ScopedImageBuffer()
    {
        if (buffer_ != nullptr) {
            MaaImageBufferDestroy(buffer_);
        }
    }

    ScopedImageBuffer(const ScopedImageBuffer&) = delete;
    ScopedImageBuffer& operator=(const ScopedImageBuffer&) = delete;

    // 交出裸句柄给 C API（MaaControllerCachedImage 需要 MaaImageBuffer*）。
    MaaImageBuffer* get() const { return buffer_; }

    // 空缓冲区也能创建成功，所以 operator bool 判的是「构造是否成功」，不是「有没有像素」。
    explicit operator bool() const { return buffer_ != nullptr; }

private:
    MaaImageBuffer* buffer_ = nullptr;
};

// 一帧的「视图」：只记录指针与形状，不持有像素。
//
// 关键语义（对应 MaaEnd 的 to_mat）：这是**视图**，不是拷贝。
// data 指向 MaaImageBuffer 内部的像素内存，buffer 一销毁它就悬空。
// 所以：要么在 buffer 存活期间用完，要么自己 memcpy 出去。
// ImageView 是 MaaEnd `utils.h` 里 to_mat() 的等价物，但不引入 OpenCV：
// 只记指针与形状，让上层自己按 channels 步长走。
// 为什么强调「视图」：像素内存属于 MaaImageBuffer，
// buffer 一销毁（含析构离开作用域），这里 data 就是悬空指针 —— MaaEnd 的 to_mat 同病。
struct ImageView
{
    // const uint8_t*：只读视图，防止调用方误改框架内部内存。
    const uint8_t* data = nullptr;
    int width = 0;
    int height = 0;
    int channels = 0;
    int type = 0;

    // empty()：字段太多，用一次判断代替到处写 `data && width > 0 && height > 0`。
    bool empty() const { return data == nullptr || width <= 0 || height <= 0; }
};

// to_view：把 C 句柄翻译成视图。返回值是**拷贝出来的结构体**，但里面的指针仍指向 buffer。
ImageView to_view(const MaaImageBuffer* buffer)
{
    ImageView view;
    // 空句柄直接返回默认值，避免解引用空指针。
    if (buffer == nullptr) {
        return view;
    }

    // MaaImageBufferGetRawData 返回 void*，需要 static_cast 成字节指针。
    view.data = static_cast<const uint8_t*>(MaaImageBufferGetRawData(buffer));
    // 宽高通道数都是独立 C API；它们只是读元数据，不拷贝像素。
    view.width = MaaImageBufferWidth(buffer);
    view.height = MaaImageBufferHeight(buffer);
    view.channels = MaaImageBufferChannels(buffer);
    // type 是 OpenCV 的类型编号：CV_8UC3 = 16（CV_8U=0，通道数 3 → (3-1)<<3）。
    // 打印它就能确认「8 位无符号、3 通道」，不必依赖 channels 一个字段。
    view.type = MaaImageBufferType(buffer);
    return view;
}

// 某个通道的均值。void* 转成字节指针后按 channels 步长跳。
// 某一个通道的均值。L1 用它证明通道顺序（BGR 还是 RGB）。
double channel_mean(const ImageView& view, int channel)
{
    // 三道防御：空视图、通道号为负、通道号越界。
    if (view.empty() || channel < 0 || channel >= view.channels) {
        return 0.0;
    }

    // 像素总数。先转 size_t 再乘，避免 int 溢出（1280*720 = 921600，int 装得下，但习惯要稳）。
    const size_t pixel_count = static_cast<size_t>(view.width) * static_cast<size_t>(view.height);
    if (pixel_count == 0) {
        return 0.0;
    }

    // uint64 累加：921600 个像素 × 255 ≈ 2.35 亿，uint32 也够，但用更宽的类型避免思考。
    uint64_t sum = 0;
    for (size_t i = 0; i < pixel_count; ++i) {
        // 按 channels 步长跳：第 i 个像素的第 channel 个字节，
        // 偏移 = i * channels + channel。这就是交错存储（interleaved）的 BGR/BGRA 布局。
        sum += view.data[i * static_cast<size_t>(view.channels) + static_cast<size_t>(channel)];
    }
    return static_cast<double>(sum) / static_cast<double>(pixel_count);
}

// 把缓冲区的 PNG 编码直接写盘。MaaFramework 内部做编码，所以不需要 OpenCV。
// 落盘 PNG：走 MaaImageBufferGetEncoded，编码由框架内部的 imencode 完成。
bool save_png(const MaaImageBuffer* buffer, const std::string& path)
{
    // GetEncoded 返回 PNG 字节流（uint8_t*），长度要另外问 GetEncodedSize。
    // 这就是为什么 L1 不需要 OpenCV：编码在框架里，我们只做文件写入。
    const uint8_t* encoded = MaaImageBufferGetEncoded(buffer);
    const MaaSize size = MaaImageBufferGetEncodedSize(buffer);
    // 空指针或 0 长度：编码失败或缓冲区为空，直接报错，不要写出 0 字节文件。
    if (encoded == nullptr || size == 0) {
        log_error("MaaImageBufferGetEncoded returned empty");
        return false;
    }

    // 用 C 的 fopen 而不是 std::ofstream：路径是窄字符串，Windows 码页问题在 Linux 上不存在。
    std::FILE* file = std::fopen(path.c_str(), "wb");
    if (file == nullptr) {
        log_error("cannot open output file: " + path);
        return false;
    }

    // fwrite 返回实际写入的元素数（每元素 1 字节），与 size 比对可发现磁盘满等短写。
    const size_t written = std::fwrite(encoded, 1, static_cast<size_t>(size), file);
    // 关闭文件。即使 fwrite 失败也要关，否则句柄泄漏。
    std::fclose(file);

    // 短写检查：不加这句，磁盘满时程序会以为成功。
    if (written != static_cast<size_t>(size)) {
        log_error("short write: " + std::to_string(written) + "/" + std::to_string(size));
        return false;
    }

    log_info("saved " + path + " (" + std::to_string(size) + " bytes, PNG)");
    return true;
}

// 拼 config_json。与 L0 完全相同的三个字段，L1 只是多了抓帧动作。
std::string build_config_json(const std::string& socket_path)
{
    std::string json = "{";
    // screencap_method / input_method 是必填；这里都填 Wlr。
    // 转义 \" 是因为 JSON 的键必须带引号，而这个字符串本身是 C++ 字面量。
    json += "\"screencap_method\": " + std::to_string(kScreencapMethodWlr) + ",";
    json += "\"input_method\": " + std::to_string(kInputMethodWlr) + ",";
    json += "\"wlr_socket_path\": \"" + socket_path + "\",";
    // use_win32_vk_code：L1 用不到按键，但保持与 L0 一致，
    // 将来接 L3 的 pipeline 时不会因为漏了这个字段而按键错位。
    json += "\"use_win32_vk_code\": true";
    json += "}";
    return json;
}

// 连接：提交任务 → 等待 → 判状态。与 L0 相同，L1 复用。
bool connect_controller(MaaController* controller)
{
    // PostConnection 返回 MaaCtrlId（int64 别名）。空句柄时 C API 返回 false，即 0，
    // 而 0 就是 MaaInvalidId，所以判 0 等价于「提交失败」。
    const MaaCtrlId job_id = MaaControllerPostConnection(controller);
    if (job_id == 0) {
        log_error("MaaControllerPostConnection returned invalid id");
        return false;
    }

    // Wait 会阻塞到任务结束并返回最终状态。
    // 4000 = MaaStatus_Failed，3000 = Succeeded（见 MaaDef.h）。
    const MaaStatus status = MaaControllerWait(controller, job_id);
    if (status != MaaStatus_Succeeded) {
        log_error("connect failed, status = " + std::to_string(status));
        return false;
    }

    return true;
}

// 抓一帧：提交任务 → 等待 → 取缓存图。返回耗时（毫秒），失败返回 -1。
// 抓一帧并计时。返回毫秒数，失败返回 -1（调用方用 <0 判失败，比传引用更简单）。
double grab_once(MaaController* controller, MaaImageBuffer* buffer)
{
    // steady_clock：单调时钟，适合测量间隔。
    const auto begin = std::chrono::steady_clock::now();

    // PostScreencap 是异步的：只是排队，立刻返回 job id。
    // 真正的截图发生在框架的 action 线程里。
    const MaaCtrlId job_id = MaaControllerPostScreencap(controller);
    if (job_id == 0) {
        log_error("MaaControllerPostScreencap returned invalid id");
        return -1.0;
    }

    // 等待截图任务结束。这一步的耗时才是「抓一帧」的真实成本。
    const MaaStatus status = MaaControllerWait(controller, job_id);
    if (status != MaaStatus_Succeeded) {
        log_error("screencap failed, status = " + std::to_string(status));
        return -1.0;
    }

    // CachedImage 把最近一帧拷进我们传进去的 buffer。
    // 注意：它取的是**缓存帧**，若刚 Wait 成功，缓存就是刚抓的那帧。
    // 如果跳过 PostScreencap 直接调它，会拿到旧帧（docs/03 里有这条坑）。
    if (!MaaControllerCachedImage(controller, buffer)) {
        log_error("MaaControllerCachedImage returned false");
        return -1.0;
    }

    // 结束计时，返回毫秒（duration<double, milli> 保留小数）。
    const auto end = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(end - begin).count();
}

// 分位数。传值是为了能就地排序，不影响调用方的 vector。
double percentile(std::vector<double> values, double ratio)
{
    if (values.empty()) {
        return 0.0;
    }

    // 排序后按下标取。样本只有 20 个，插入排序也够快，std::sort 足够。
    std::sort(values.begin(), values.end());
    const size_t index = static_cast<size_t>(ratio * static_cast<double>(values.size() - 1));
    return values[std::min(index, values.size() - 1)];
}

// 命令行选项，全部带默认值，所以不带参数也能跑（用默认 socket 与 20 帧）。
struct Options
{
    std::string socket_path = kDefaultSocketPath;
    std::string out_path = "frame.png";
    int frames = kDefaultFrames;
};

// 极简参数解析：--out 路径、--frames 数量、其余位置参数当 socket 路径。
Options parse_args(int argc, char** argv)
{
    Options options;
    // 从 1 开始：argv[0] 是程序名。
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--out" && i + 1 < argc) {
            options.out_path = argv[++i];
        }
        else if (arg == "--frames" && i + 1 < argc) {
            options.frames = std::atoi(argv[++i]);
        }
        // 不是 --out / --frames 的参数就当 socket 路径 —— 与 L0 的用法兼容。
        else {
            options.socket_path = arg;
        }
    }
    return options;
}

} // namespace mini

// main：与 L0 同构，多了抓帧与统计三段。
int main(int argc, char** argv)
{
    const mini::Options options = mini::parse_args(argc, argv);

    // 先打版本。它同时验证「头文件版本」与「动态库版本」一致 ——
    // 如果头文件是 5.14、加载到的是别的版本，某些结构体布局会不匹配。
    mini::log_info(std::string("MaaFramework version: ") + MaaVersion());

    const std::string config = mini::build_config_json(options.socket_path);
    // MaaLinuxControllerCreate 只收 JSON 字符串，返回不透明句柄。
    // 失败返回 nullptr，立刻被 ScopedController 包住（即使为空也安全）。
    mini::ScopedController controller(MaaLinuxControllerCreate(config.c_str()));
    if (!controller) {
        mini::log_error("MaaLinuxControllerCreate returned nullptr");
        return 1;
    }

    // 连接失败就退 1：脚本据此判断环境是否就绪。
    if (!mini::connect_controller(controller.get())) {
        return 1;
    }
    mini::log_info("connected = true");

    // 缓冲区的生命周期必须覆盖所有使用它的 view —— 所以它在 main 里声明，晚于 controller 销毁。
    mini::ScopedImageBuffer image;
    if (!image) {
        mini::log_error("MaaImageBufferCreate returned nullptr");
        return 1;
    }

    // 第一帧：尺寸、通道、通道均值、落盘。
    // 第一帧：同时拿到耗时与像素。
    const double first_ms = mini::grab_once(controller.get(), image.get());
    if (first_ms < 0.0) {
        return 1;
    }

    // 取视图。此刻 buffer 活着，view 有效；一旦 main 结束（image 析构），view 就悬空。
    // 本程序所有使用都在 main 内，所以安全 —— 这正是 MaaEnd 那条「to_mat 是视图」的纪律。
    const mini::ImageView view = mini::to_view(image.get());
    mini::log_info(
        "frame = " + std::to_string(view.width) + "x" + std::to_string(view.height) + ", channels = " + std::to_string(view.channels)
        + ", type = " + std::to_string(view.type) + ", first_frame = " + std::to_string(first_ms) + " ms");

    // 通道均值。合成器背景是 #1b2b34（R=27 G=43 B=52），若按 BGR 读应得 B>G>R。
    // 三个通道的均值。通道 0/1/2 在 BGR 布局下分别是 B/G/R。
    // 这就是「肉眼校正」的依据：合成器背景 #1b2b34（R=27 G=43 B=52），
    // 若打印出 [52, 43, 27] 说明通道序是 BGR；若打印 [27, 43, 52] 则是 RGB。
    const double mean_b = mini::channel_mean(view, 0);
    const double mean_g = mini::channel_mean(view, 1);
    const double mean_r = mini::channel_mean(view, 2);
    mini::log_info("channel mean BGR = [" + std::to_string(mean_b) + ", " + std::to_string(mean_g) + ", " + std::to_string(mean_r) + "]");

    // 存 PNG。文件名来自 --out，默认 frame.png。
    if (!mini::save_png(image.get(), options.out_path)) {
        return 1;
    }

    // 截图之后再看分辨率：L0 里没截图所以是 false，现在应该给真值。
    // 截图之后再查分辨率。L0 里这一步返回 false（缓存为空），
    // 现在应该给出 1280x720 —— 这条同时验证了 L0 学到的语义。
    int32_t raw_width = 0;
    int32_t raw_height = 0;
    if (MaaControllerGetResolution(controller.get(), &raw_width, &raw_height)) {
        mini::log_info("resolution = " + std::to_string(raw_width) + "x" + std::to_string(raw_height));
    }
    else {
        mini::log_info("resolution unavailable (unexpected after screencap)");
    }

    // 多帧计时。
    // 多帧计时容器：先 reserve，避免循环里反复扩容。
    std::vector<double> samples;
    samples.reserve(static_cast<size_t>(options.frames));
    // 抓 N 帧，每帧耗时入样本。失败立即退出，不静默跳过。
    for (int i = 0; i < options.frames; ++i) {
        const double cost_ms = mini::grab_once(controller.get(), image.get());
        if (cost_ms < 0.0) {
            return 1;
        }
        samples.push_back(cost_ms);
    }

    if (!samples.empty()) {
        // 结构化绑定取最小/最大迭代器（C++17 起）。
        const auto [min_it, max_it] = std::minmax_element(samples.begin(), samples.end());
        mini::log_info(
            "screencap x" + std::to_string(samples.size()) + " ms: min = " + std::to_string(*min_it)
            + ", median = " + std::to_string(mini::percentile(samples, 0.5)) + ", p95 = " + std::to_string(mini::percentile(samples, 0.95))
            + ", max = " + std::to_string(*max_it));
    }

    // 成功退出 0。
    return 0;
}
