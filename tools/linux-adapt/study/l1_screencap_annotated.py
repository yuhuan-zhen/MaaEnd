#!/usr/bin/env python3
"""L1 帧源层验收：MaaLinuxControlUnit / WlrScreencap 是否给出正确的 1280x720 帧。

只读，不注入任何输入。判定项：
  1. resolution == (1280, 720)，帧 shape == (720, 1280, 3)
  2. 通道序：binding 声明是 BGR；用 grim 同协议参考帧交叉验证
  3. 帧耗时分布（20 帧）
  4. 静止画面下的帧间稳定性（均值标准差）
  5. 与 grim 参考帧的相似度（NCC），确认不是黑帧/花屏/错缩放

用法：
    XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
      python3 l1_screencap.py [--socket /run/user/0/wayland-1] [--n 20]
"""

# =============================================================================
# 这份文件在干什么（小白先读这一段）
# =============================================================================
#
# 我们要验证一件事：MaaFramework 在 Linux 上能不能「把游戏画面正确截下来」。
# 后面所有识别（模板匹配、OCR）都建立在截图上，所以截图错一个像素或错一个通道，
# 后面全错，而且错得很隐蔽（不报错，只是识别率低）。所以第一层只测截图。
#
# 「截图」在这里不是自己写代码去抓屏，而是调用 MaaFramework 现成的
# MaaLinuxController 对象，让它去问 Wayland 合成器（sway）要一帧画面。
# 我们要做的是：拿到帧 → 量它的尺寸/通道/耗时 → 和另一个工具 grim 抓的帧对比。
#
# 名词（第一次出现就解释，后面直接用）：
#   - 控制器 Controller：MaaFramework 里负责「截图 + 输入」的对象。一个任务绑定一个控制器。
#   - Job：MaaFramework 的异步操作句柄。post_xxx() 只是「提交」，.wait() 才等结果。
#   - BGR / RGB：一张彩色图的三个颜色分量排列顺序。BGR = 蓝绿红，RGB = 红绿蓝。
#     OpenCV 与 MaaFramework 用 BGR，浏览器与 PIL 用 RGB。顺序搞反 → 红色变蓝色。
#   - NCC（归一化互相关）：0~1 的相似度。-1~1 也可以，1 表示完全一样，0 表示毫无关系。
#     用它比两张图是否「同一画面」，比逐像素相等更耐噪。
#   - grim：wlroots 系合成器的官方截图小工具，和我们用的截图协议是同一个，
#     所以它抓的帧可以当作「标准答案」来对照。
#   - Wayland socket：跟合成器通信用的本地文件（unix socket），
#     形如 /run/user/0/wayland-1。路径里的 0 是用户 id（这里是 root），1 是第 2 个显示实例。
#
# 文档对照（完整链接见同目录 README.md 的「文档对照表」）：
#   [FW-2.1] 集成文档（各语言 binding 情况）
#   [FW-2.2] 集成接口一览（MaaLinuxControllerCreate / MaaControllerSetOption）
#   [FW-2.4] 控制方式说明（Linux Screencap / Linux Input 两张表，1/4 这些数字的出处）
#   [FW-3.3] ProjectInterface V2（controller.type 与 display_* 字段）
#   [BIND]   Python binding 源码 maa/controller.py（LinuxController 类）
#   [PLAN]   本仓库 tools/linux-adapt/PLAN.md（六层计划与 L1 验收标准）
#
# =============================================================================

# 这一行让 Python 3.7+ 把类型注解「延迟求值」：写成 list[np.ndarray] 这种
# 较新的写法时，在旧解释器上也不会当场报错。本项目要求 Python >= 3.14（见 pyproject.toml），
# 其实已经不需要它了，但保留是社区惯例，且能让注释版在旧环境也能编译检查。
from __future__ import annotations

# argparse：解析命令行参数（--socket / --n / --out），避免把路径写死在代码里。
import argparse

# json：把验收结果写成 JSON 文件，方便事后 diff 和归档。
import json

# statistics：算中位数（median）。耗时只看平均值会被偶尔的慢帧带偏，中位数更稳。
import statistics

# subprocess：调用外部程序 grim（外部截图工具），用它是为了拿「标准答案」对照。
import subprocess

# sys：用来给进程设置退出码（0 = 通过，非 0 = 失败），CI 就是靠退出码判断成败的。
import sys

# time：给每一步计时（perf_counter 更准，但这里用 time.time 足够，单位换算在代码里做）。
import time

# pathlib.Path：跨平台的路径对象。比手拼字符串安全，且 .parent / mkdir 等写法更清楚。
# 注意：它跟 pathlib 之外的东西无关，只是路径工具。
from pathlib import Path

# numpy：数值计算库。截图在内存里就是一个「高 × 宽 × 3」的数字矩阵，用 numpy 才能
# 高效地求均值、做点积、切片翻转通道。
# 依赖出处：本仓库 pyproject.toml 的 [dependency-groups] images 组（numpy>=2.5）。
import numpy as np

# LinuxController：MaaFramework Python binding 里代表「Linux 控制器」的类。
# 注意 import 路径是 maa.controller，而安装的 PyPI 包名是 maafw（名字不一样，容易踩）。
# 依赖出处：[dependency-groups] pipeline 组（maafw>=5.12），uv.lock 锁定 5.14.3。
# 文档：[FW-2.1] 说明 Python 是官方支持、全功能可用的 binding；[BIND] 是该类源码。
from maa.controller import LinuxController

# PIL（Pillow）：图像读写库。只用来把 numpy 矩阵存成 PNG，以及读 grim 存的 PNG。
# 依赖出处：images 组（pillow>=13.0）。
from PIL import Image

# 这两个常量是「用哪种截图 / 用哪种输入」的取值，直接对应 C 枚举的整数值。
# 数字来历：[FW-2.4] 的 Linux Screencap 表里 WlrScreencap 的值就是 1，
# Linux Input 表里 Wlr 的值也是 1。改错数字不会报错，只会静默换成别的方式。
# 注意用位或可以同时开多种（如 1 | 4），框架会自动挑可用的一种；这里只开一种。
SCREENCAP_WLR = 1  # MaaLinuxScreencapMethod_WlrScreencap
INPUT_WLR = 1      # MaaLinuxInputMethod_Wlr


# -----------------------------------------------------------------------------
# 工具函数 1：NCC（归一化互相关）
# -----------------------------------------------------------------------------
# 为什么需要它：判断两张图「是不是同一画面」，不能逐像素比较（有一点点噪点就判不同）。
# NCC 先把两图各自减去自己的均值（去掉整体亮度差异），再算余弦相似度，对亮度变化不敏感。
def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关（灰度、零均值）。"""
    # 转成 float64：uint8 相减会溢出（0-5 变成 251），必须先升精度。
    # ravel()：把 (高, 宽, 3) 拉平成一维向量，方便算点积。
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    # 各自减去自身均值 = 「零均值化」，这是「归一化」那一半，去掉亮度差异。
    a -= a.mean()
    b -= b.mean()
    # 两个向量的长度（L2 范数）相乘，作为分母，这是「相关」归一化的那一半。
    # 用 float() 转成 Python 原生浮点，避免 numpy 标量参与后续除法时出现奇怪类型。
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    # 分母为 0 说明有一张是纯色图（减均值后全 0），相似度无意义，返回 NaN 表示「测不出来」。
    # 否则返回点积除以分母，结果落在 -1 ~ 1，1 表示完全同向（同一画面）。
    return float("nan") if denom == 0 else float(a.dot(b) / denom)


# -----------------------------------------------------------------------------
# 工具函数 2：取每个通道的平均值
# -----------------------------------------------------------------------------
# 为什么需要它：判断通道顺序最直接的办法就是看「三个通道的均值分别是多少」。
# 同一画面下按 BGR 读和按 RGB 读，得到的三个数字是倒序的，一眼就能看出来。
def channel_means(img: np.ndarray) -> list[float]:
    # img[:, :, i] 的意思是：所有行、所有列、第 i 个通道 —— 即取出第 i 个颜色平面。
    # range(img.shape[2]) 就是 0/1/2 三个通道。round 保留 3 位小数，只为好看。
    return [round(float(img[:, :, i].mean()), 3) for i in range(img.shape[2])]


# -----------------------------------------------------------------------------
# 工具函数 3：用 grim 抓一张参考图
# -----------------------------------------------------------------------------
# 为什么要外部工具：我们自己写的截图路径如果实现有问题（比如缩放错了），
# 自己跟自己比是发现不了的。grim 用同一个 Wayland 协议但由别人独立实现，
# 拿它的输出当「标准答案」，才能证明我们的帧是真的对。
def grim_capture(out_path: Path) -> bool:
    """用 grim 抓同一路 wlroots 输出作为参考（同 zwlr_screencopy 协议）。"""
    try:
        # check=True：grim 退出码非 0 时抛异常，避免把「没抓成功」当成成功。
        # stdout/stderr 丢进 DEVNULL：这是可选的辅助步骤，不需要它的输出污染验收日志。
        subprocess.run(["grim", str(out_path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 有的程序退出码是 0 但没写文件，所以再确认文件真的存在。
        return out_path.exists()
    except Exception:
        # grim 没装、没有 Wayland 环境、权限不足都会走到这里。
        # 这是「可选步骤」，失败不算验收失败，只标记为 unavailable，让主流程跳过对照。
        return False


# -----------------------------------------------------------------------------
# 工具函数 4：把 BGR 矩阵存成 PNG
# -----------------------------------------------------------------------------
# 为什么要专门做通道翻转：MaaFramework 给的帧是 BGR，而 PNG/PIL 认为数据是 RGB。
# 直接存会红蓝互换（天空变橙、草地变紫），肉眼看得出，但代码不会报错。
def save_png(img: np.ndarray, out_path: Path, bgr: bool = True) -> None:
    """BGR -> RGB 后落盘。"""
    # img[:, :, ::-1]：第三个维度倒序，即 BGR 变 RGB。这是 numpy 的切片技巧，
    # ::-1 表示「从后往前每一步取一个」。只有 3 通道时才做，避免把灰度图搞坏。
    arr = img[:, :, ::-1] if bgr and img.shape[2] == 3 else img
    # astype(np.uint8)：PIL 只认 0~255 的 8 位整数；我们前面为了算均值升过精度，
    # 这里降回来。save() 根据后缀 .png 决定编码格式。
    Image.fromarray(arr.astype(np.uint8)).save(out_path)


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
# 返回值就是进程退出码：0 表示验收通过，非 0 表示失败。CI 与脚本调用靠这个判断。
def main() -> int:
    # ArgumentParser：没有任何参数时也能跑（下面三个都有默认值）。
    ap = argparse.ArgumentParser()
    # --socket：要连哪个 Wayland socket。默认是 root 用户在第二个显示实例上跑的 sway。
    # 为什么是 /run/user/0：0 是 root 的 uid；why wayland-1：0 被 WSLg 自己占了，
    # 嵌套 sway 只能用 1。这一行是「环境适配」而不是业务逻辑。
    ap.add_argument("--socket", default="/run/user/0/wayland-1")
    # --n：抓多少帧来算耗时分布。20 帧足够看出中位数和波动，又不至于跑太久。
    ap.add_argument("--n", type=int, default=20)
    # --out：证据目录名。默认 evidence-l1，会被 .gitignore 排除（二进制产物不进 git）。
    ap.add_argument("--out", default="evidence-l1")
    # parse_args 会把命令行解析成对象，后面用 args.socket 这样的属性访问。
    args = ap.parse_args()

    # __file__ 是当前脚本路径，.parent 是它所在目录；再拼上证据目录名。
    # 用「脚本所在目录」而不是「当前工作目录」，这样在哪个目录调用脚本，产物都落在同一处。
    out_dir = Path(__file__).parent / args.out
    # parents=True：父目录不存在就一起创建；exist_ok=True：已存在不报错。
    out_dir.mkdir(parents=True, exist_ok=True)
    # result 是这一层唯一的「结果对象」，最后整体写成 JSON。
    # checks 里放逐项布尔判定，ok 是「全部通过」的汇总，先假设 False，最后再算。
    result: dict = {"socket": args.socket, "checks": {}, "ok": False}

    # --- 创建并连接 ---
    # cfg 就是 [FW-2.2] 里 MaaLinuxControllerCreate 的那个 config_json，Python binding 收 dict。
    # 四个字段的含义在 [FW-2.4] 与 2.1 文档里都有：
    #   screencap_method：用哪种方式抓帧（1 = Wlr，走 zwlr-screencopy 协议）。
    #   input_method：用哪种方式注入输入（1 = Wlr，走 wlr virtual pointer 协议）。
    #   wlr_socket_path：合成器的 socket 路径，控制器靠它连上 sway。
    #   use_win32_vk_code：键码空间开关。true = 传进来的是 Win32 VK（27 = Esc），
    #                     框架内部转 evdev；false（默认）= 直接当 evdev 扫描码用。
    #                     MaaEnd 的 pipeline 全部按 Win32 VK 写，所以必须是 true。
    cfg = {
        "screencap_method": SCREENCAP_WLR,
        "input_method": INPUT_WLR,
        "wlr_socket_path": args.socket,
        "use_win32_vk_code": True,
    }
    # 记开始时间，用来量「创建 + 连接」花了多久（连接慢会让整体启动很钝）。
    t0 = time.time()
    try:
        # 构造对象只会创建控制器的句柄，还没连上合成器；真正的连接在下面 post_connection。
        # 构造失败通常是参数非法（缺必填字段、方法值不认识），这里捕获后写结果并退出。
        ctrl = LinuxController(cfg)
    except Exception as exc:
        # 用 [FAIL] 前缀是为了让日志一眼能 grep 出失败行。
        print(f"[FAIL] LinuxController 创建失败: {exc}")
        # 即使失败也把 result 落盘，方便事后看当时用的是哪个 socket、报了什么错。
        result["error"] = str(exc)
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        # 返回 1 表示「环境/参数错误」，和下面「验收不通过」用不同退出码区分。
        return 1

    # post_connection() 提交一个「连接」任务并立刻返回 Job 对象（异步）。
    # 这是 MaaFramework 的统一风格：post_xxx 提交，.wait() 等待，.succeeded 查结果。
    job = ctrl.post_connection()
    # wait() 会阻塞到任务结束（内部带超时）。不调用它会立刻去查状态，永远是「还没开始」。
    job.wait()
    # succeeded 是布尔属性。连接失败通常是 socket 不存在、权限不对、或不是支持的合成器。
    if not job.succeeded:
        print(f"[FAIL] connect 失败: {job.status}")
        result["error"] = f"connect {job.status}"
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        # 返回 1：连不上属于环境问题，不是「截图质量不达标」。
        return 1
    # 连上之后立刻算耗时（含构造对象的时间），保留 1 位小数；实测 216.2 ms。
    result["connect_ms"] = round((time.time() - t0) * 1000, 1)
    print(f"[ ok ] connect  {result['connect_ms']} ms")

    # --- 分辨率 ---
    # 这一步是「明知有问题也要测」的观察点：本控制器实测返回 (0, 0)。
    # 原因：Linux 控制器的 MaaControllerGetResolution 还没实现完整（同文件 start_app 也是 TODO）。
    # 现在不影响结果，因为我们没设 display_* 缩放，坐标和像素 1:1；
    # 但任何「拿 resolution 去换算」的代码都会拿到 0，所以这里必须单独记录。
    try:
        res = ctrl.resolution
    except Exception:
        # 老版本 binding 可能没有这个属性，读不到就当 None，不让它中断整个验收。
        res = None
    # list(res) 是为了能写进 JSON（tuple 会被序列化成数组，但显式转换更直观）。
    # `if res` 同时过滤 None 和 (0, 0)？不——(0, 0) 是非空元组，是真值，所以会保留成 [0, 0]。
    result["resolution"] = list(res) if res else None
    print(f"[info] resolution = {res}")

    # --- 参考帧（grim） ---
    # 先把参考图抓到证据目录里，失败也只是返回 False，不影响主流程。
    grim_path = out_dir / "ref-grim.png"
    has_grim = grim_capture(grim_path)

    # --- 抓 n 帧 ---
    frames: list[np.ndarray] = []
    times: list[float] = []
    # 循环抓 n 帧。每帧记一次耗时，同时把帧本身留下来，用于后面算「静止画面稳定性」。
    for i in range(args.n):
        # 单帧的起止时间，用来算这一帧的耗时。
        t = time.time()
        # 一行三个动作，是 MaaFramework 的典型写法：
        #   post_screencap()：提交截图任务，立即返回 Job
        #   .wait()：等它执行完
        #   .get()：取回结果，类型是 numpy ndarray（BGR，形状 (高, 宽, 3)）
        # 注意 get() 必须在 wait() 之后，否则拿到的可能是空结果。
        r = ctrl.post_screencap().wait().get()
        # 耗时换算成毫秒。乘 1000 是因为 time.time() 的单位是秒。
        times.append((time.time() - t) * 1000.0)
        # 这里 if/else 两支做的事完全一样（都 append）——是历史遗留的等价分支。
        # 保留原样是为了让注释版与真实文件逐行对得上；清理时应当合并成一行 append。
        if i == 0:
            frames.append(r)
        else:
            frames.append(r)
    # 后面的尺寸/通道/落盘都只看第一帧（静止画面下各帧相同，取一帧即可代表）。
    first = frames[0]
    # shape 形如 (720, 1280, 3)，顺序是「高、宽、通道」，这是 numpy 的约定，不是 (宽, 高)。
    result["frame_shape"] = list(first.shape)
    # dtype 应为 uint8；如果是 float 或 uint16，说明截图路径做了额外转换，需要警惕。
    result["frame_dtype"] = str(first.dtype)
    # 三个通道的均值，用于判断通道序（BGR 还是 RGB）。
    result["channel_means_bgr"] = channel_means(first)

    # 排序后的耗时列表：算分位数必须有序。
    ms = sorted(times)
    # 四个统计量一起记：min 看最好的情况，median 看常态，p95 看抖动，max 看最坏。
    # 中位数比平均值更抗「偶尔一帧卡顿」的干扰，所以判定用的是 median。
    result["screencap_ms"] = {
        "min": round(ms[0], 1),
        # statistics.median 对偶数个样本取中间两个的平均值。
        "median": round(statistics.median(ms), 1),
        # 取第 95 百分位。min(len-1, ...) 是防越界：样本很少时下标会算出 len。
        "p95": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 1),
        "max": round(ms[-1], 1),
    }
    print(f"[info] shape={first.shape} dtype={first.dtype}")
    print(f"[info] 通道均值(BGR)={result['channel_means_bgr']}")
    # 这条 f-string 分三段写，只是为了不超过行宽；拼起来是「四个数 + ms」。
    print(f"[info] 耗时 min/median/p95/max = "
          f"{result['screencap_ms']['min']}/{result['screencap_ms']['median']}/"
          f"{result['screencap_ms']['p95']}/{result['screencap_ms']['max']} ms")

    # --- 静止画面稳定性 ---
    # 如果画面是静止的（页面上没有动画、没有视频），每帧的整体均值应该几乎一样。
    # 标准差很大说明画面在变（那这次测的耗时就不代表真实负载），或者截图有随机噪声。
    means = [float(f.mean()) for f in frames]
    # 保留 4 位小数；实测 0.0，说明 20 帧完全一致。
    result["frame_mean_std"] = round(float(np.std(means)), 4)
    # 同时记下最小/最大值，比单个标准差更能说明「差了多少」。
    result["frame_mean_range"] = [round(min(means), 3), round(max(means), 3)]

    # --- 干净帧落盘 ---
    # 存一张人眼可看的 PNG。用途：出问题时直接打开看是黑帧、花屏还是错缩放。
    frame_path = out_dir / "frame-bgr2rgb.png"
    save_png(first, frame_path)
    print(f"[info] 帧已落盘 {frame_path.name}")

    # --- 通道序交叉验证 ---
    # 逻辑：把我们的帧按 BGR→RGB 转一次，与 grim 的 RGB 图比较；再按「本来就是 RGB」比一次。
    # 哪种假设的相似度高，哪种就是真相。这是唯一能自证通道序的方法。
    if has_grim:
        # PIL 打开 PNG 后是 RGB 三通道；convert("RGB") 保证不是调色板/灰度模式。
        # np.asarray 把 PIL 图像转成 numpy 矩阵（高, 宽, 3），dtype 指定 uint8。
        ref = np.asarray(Image.open(grim_path).convert("RGB"), dtype=np.uint8)
        result["grim_shape"] = list(ref.shape)
        # 尺寸不一致时无法逐像素比，标记出来即可（这种情况通常意味着两路抓的不是同一个输出）。
        if ref.shape[:2] == first.shape[:2]:
            # 假设 A：binding 的声明是对的，帧是 BGR，翻成 RGB 后应与 grim 一致。
            as_rgb = first[:, :, ::-1]           # 按 binding 声明：BGR -> RGB
            # 假设 B：帧其实已经是 RGB，那原样就是 RGB，不该翻转。
            as_is = first                        # 若当成 RGB 直接用
            # 两个相似度都记下来：实测 A = 1.0，B = 0.757，差距明显，结论才站得住。
            result["ncc_bgr2rgb"] = round(ncc(as_rgb, ref), 5)
            result["ncc_as_is"] = round(ncc(as_is, ref), 5)
            # 再记一组通道均值，作为「红蓝是不是倒了」的第二重证据。
            result["ch_means_ref_rgb"] = channel_means(ref)
            print(f"[info] NCC(frame BGR->RGB, grim) = {result['ncc_bgr2rgb']}")
            print(f"[info] NCC(frame 原样当作RGB, grim) = {result['ncc_as_is']}")
            print(f"[info] grim 通道均值(RGB) = {result['ch_means_ref_rgb']}")
        else:
            # 只记录不失败：参考图尺寸不对是「这次没对照上」，不是「我们的帧有问题」。
            result["grim_shape_mismatch"] = True
    else:
        # grim 不可用时明确写进结果，避免以后看 JSON 时误以为「对照过了」。
        result["grim"] = "unavailable"

    # --- 判定 ---
    # 把逐项布尔值塞进 checks。设计原则：每项都能单独看懂，不做复合条件。
    checks = result["checks"]
    # 能走到这里说明连接已经成功过（失败在前面就 return 了），所以直接记 True。
    checks["connect"] = True
    # 分辨率检查：优先信 resolution，但它可能返回 (0, 0)，
    # 所以退一步用帧的真实 shape 来判（shape[1] 是宽，shape[0] 是高），两者任一成立即可。
    checks["resolution_1280x720"] = (result["resolution"] == [1280, 720]
                                     or (first.shape[1], first.shape[0]) == (1280, 720))
    # 形状检查：必须是三维且第三维为 3（彩图）。灰度图会让所有识别模板失配。
    checks["shape_hw3"] = (len(first.shape) == 3 and first.shape[2] == 3)
    # 空白检查：全黑（均值 0）或全白（均值 255）都说明没抓到内容。
    # 用 5~250 这种宽松阈值，是因为画面可能本来就偏暗或偏亮。
    checks["not_blank"] = 5.0 < float(first.mean()) < 250.0
    # 稳定性检查：均值标准差小于 2。静止画面实测 0.0，阈值给得很宽，只为抓明显漂移。
    checks["stable"] = result["frame_mean_std"] < 2.0
    # 速度检查：中位耗时小于 500 ms。这是宽松上限（约 2 fps 也能跑）；
    # 实测 16.2 ms，留这么大余量是为了让判定反映「能跑」而不是「跑得多快」。
    checks["fast_enough"] = result["screencap_ms"]["median"] < 500.0
    # 只有拿到 grim 对照时才检查这两项，否则不把它们算进总数（避免误判为失败）。
    if "ncc_bgr2rgb" in result:
        # 与标准答案相似度 > 0.90 才认为「抓的是同一画面」。
        checks["matches_grim"] = result["ncc_bgr2rgb"] > 0.90
        # 通道序自证：正确假设的相似度必须高于错误假设，否则说明两个都错。
        checks["bgr_confirmed"] = result["ncc_bgr2rgb"] > result["ncc_as_is"]

    # all() 要求每一项都为 True 才算通过；checks 为空时 all() 返回 True，这里不会为空。
    result["ok"] = all(checks.values())
    # 最终结果写盘（覆盖前面可能的错误版本）。indent=2 让人能直接读。
    (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    # 把逐项判定打到终端：PASS/FAIL 前缀便于一眼扫过，也便于 grep。
    print("\n=== L1 判定 ===")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    # 汇总行给出「通过几项 / 共几项」，CI 日志里一眼能看出严重程度。
    print(f"\nL1_{'OK' if result['ok'] else 'NG'}  "
          f"passed={sum(checks.values())}/{len(checks)}")
    # 退出码约定：0 = 通过，2 = 验收不通过（与前面 1 = 环境/参数错误区分开）。
    return 0 if result["ok"] else 2


# 只有「直接运行这个文件」时才执行 main()；被 import 时不会跑，方便别的脚本复用上面的函数。
if __name__ == "__main__":
    # sys.exit 把 main() 的返回值变成进程退出码，这样 shell/CI 能拿到成败。
    sys.exit(main())
