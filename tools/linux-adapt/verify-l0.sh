#!/usr/bin/env bash
# L0 肉眼验收：四个用例，逐个打印日志与退出码。
#
# 用法：
#   bash verify-l0.sh            # 跑完就退
#   bash verify-l0.sh --pause    # 每个用例后停 4 秒，方便肉眼看
#
# 依赖：sway 已在 /run/user/$UID/wayland-1 上运行（见 study/L0-肉眼验收.md 第 2 节）

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/mini-cpp/build/l0_env"
SOCKET_OK="${SOCKET_OK:-/run/user/0/wayland-1}"
SOCKET_GONE="/run/user/0/wayland-99"
SOCKET_NOT_WLROOTS="/run/user/0/wayland-0"
SWAY_CONF="/tmp/l0-sway.conf"
PAUSE=0
[ "${1:-}" = "--pause" ] && PAUSE=4

start_sway() {
    printf 'output * bg #1b2b34 solid_color\n' > "$SWAY_CONF"
    XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-0 \
        WLR_BACKENDS=wayland WLR_LIBINPUT_NO_DEVICES=1 \
        setsid sway -c "$SWAY_CONF" >> /tmp/l0-sway.log 2>&1 < /dev/null &
    sleep 4
}

if [ ! -x "$BIN" ]; then
    echo "找不到可执行文件：$BIN"
    echo "先编译：cd \"$HERE/mini-cpp\" && cmake -S . -B build -G Ninja && cmake --build build"
    exit 9
fi

run_case() {
    local tag="$1" desc="$2" socket="$3" expect="$4"
    echo "════════════════════════════════════════════════════════════════"
    echo "用例 $tag ｜ $desc"
    echo "socket = $socket   ｜ 预期：$expect"
    echo "────────────────────────────────────────────────────────────────"
    XDG_RUNTIME_DIR=/run/user/0 "$BIN" "$socket"
    local rc=$?
    echo "────────────────────────────────────────────────────────────────"
    echo ">>> 退出码 = $rc"
    echo
    [ "$PAUSE" -gt 0 ] && sleep "$PAUSE"
}

run_case A "正常连接"          "$SOCKET_OK"            "connected = true，退出码 0"
run_case B "socket 不存在"     "$SOCKET_GONE"          "3 行 ERR，退出码 1"
run_case C "非 wlroots 合成器" "$SOCKET_NOT_WLROOTS"   "bind_protocol 失败，退出码 1"

echo "════════════════════════════════════════════════════════════════"
echo "用例 D ｜ 杀掉合成器再拉回来（此刻那个深蓝灰窗口会消失、再出现）"
echo "════════════════════════════════════════════════════════════════"
pkill -x sway 2>/dev/null
pkill -x swaybg 2>/dev/null
sleep 1
run_case D1 "合成器已停止" "$SOCKET_OK" "退出码 1（socket 文件还在，但没人监听）"
start_sway
run_case D2 "合成器已恢复" "$SOCKET_OK" "connected = true，退出码 0"

echo "════════════════════════════════════════════════════════════════"
echo "协议级证据（用例 A 的 wayland 交互）"
echo "────────────────────────────────────────────────────────────────"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/0}"
WAYLAND_DEBUG=1 "$BIN" "$SOCKET_OK" 2>&1 >/dev/null | grep -E "screencopy|virtual_pointer|virtual_keyboard" | head -8
echo "════════════════════════════════════════════════════════════════"
