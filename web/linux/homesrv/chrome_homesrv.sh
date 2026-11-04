#!/usr/bin/env bash
# homesrv 版：起 sway（headless）+ Chrome（复用 M7A 自带的 Chrome for Testing）。
# 与 WSL 版等价，只是路径/浏览器不同；用户级运行，不需要 root。
set -uo pipefail

if [ -n "${MAAEND_CHROME:-}" ]; then
  CHROME="$MAAEND_CHROME"
elif [ -x "$HOME/opt/chrome/opt/google/chrome/google-chrome" ]; then
  CHROME="$HOME/opt/chrome/opt/google/chrome/google-chrome"   # 正式版，无 "for Testing" 提示条
else
  CHROME="$HOME/m7a/3rdparty/WebBrowser/chrome/linux64/140.0.7339.207/chrome"
fi
PROFILE="${MAAEND_PROFILE:-$HOME/.config/endfield-web}"
URL="${1:-https://endfield.hypergryph.com/cloud}"
# cron 里没有 XDG_RUNTIME_DIR，会落到 /tmp/xdg-run；实测那样点击不生效。
# 统一到用户 session 的运行时目录（存在才用），与手动运行保持一致。
if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -d "${XDG_RUNTIME_DIR:-}" ]; then
  if [ -d "/run/user/$(id -u)" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
  else
    export XDG_RUNTIME_DIR="/tmp/xdg-run"
  fi
fi
RUNTIME="$XDG_RUNTIME_DIR"
SWAY_CONF=/tmp/endfield-sway.conf

export XDG_RUNTIME_DIR="$RUNTIME"
export XDG_SESSION_TYPE=wayland
export WAYLAND_DISPLAY=wayland-1
mkdir -p "$RUNTIME" "$PROFILE"; chmod 700 "$RUNTIME"

# 物理输出与缩放可调：默认 2560x1440 + Chrome DSF 1.5 → CSS 1706x960。
# 云网页版用 SwiftShader 软渲染，像素数直接决定 CPU：720p 大约只需 1/4。
# 例：MAAEND_RES=1280x720 MAAEND_DSF=1 MAAEND_WIN=1280,720 ./chrome_homesrv.sh
# 生产几何：同目录 geometry.conf（set_geometry.sh 720p|1440p 一键切换，可回档）。
# 优先级：显式 MAAEND_* 环境变量 > geometry.conf > 下面这行的内置默认。
if [ -z "${MAAEND_RES:-}" ] && [ -f "$(dirname "$0")/geometry.conf" ]; then
  . "$(dirname "$0")/geometry.conf"
fi

SWAY_RES="${MAAEND_RES:-2560x1440}"
CHROME_DSF="${MAAEND_DSF:-1.5}"
CHROME_WIN="${MAAEND_WIN:-1706,960}"
# 防御 CRLF 配置：geometry.conf 若被 Windows 编辑器保存过，source 进来的值会带 \r，
# 视口校验会变成「1280x720 ≠ 1280x720\r」并无限重启 Chrome。
CHROME_WIN="${CHROME_WIN//$'\r'/}"
printf '%s\n' \
  "output HEADLESS-1 resolution $SWAY_RES scale 1" \
  'output HEADLESS-1 bg #000000 solid_color' \
  'default_border none' > "$SWAY_CONF"

if pgrep -x sway >/dev/null 2>&1 && [ ! -S "$RUNTIME/wayland-1" ]; then
  echo "[i] 检测到 sway 跑在别的 socket 上，重启到 $RUNTIME"
  pkill -x swaybg 2>/dev/null; pkill -x sway 2>/dev/null; sleep 2
fi

if ! pgrep -x sway >/dev/null 2>&1; then
  echo "[i] 起 sway"
  WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman LIBSEAT_BACKEND=noop \
    setsid sway -c "$SWAY_CONF" </dev/null >/tmp/sway-endfield.log 2>&1 &
  for i in $(seq 1 15); do sleep 1; [ -S "$RUNTIME/wayland-1" ] && break; done
fi

pkill -f "user-data-dir=$PROFILE" 2>/dev/null
sleep 2
# 强杀会留下 Singleton 锁，下一次 Chrome 会立刻退出（表现为"启动浏览器失败"）
rm -f "$PROFILE"/SingletonLock "$PROFILE"/SingletonCookie "$PROFILE"/SingletonSocket "$PROFILE"/lockfile 2>/dev/null
launch_chrome() {
  setsid "$CHROME" \
    --ozone-platform=wayland \
    --test-type \
    --lang=zh-CN \
    --force-device-scale-factor="$CHROME_DSF" \
    --no-sandbox --test-type \
    --window-size="$CHROME_WIN" --kiosk \
    --use-angle=swiftshader --enable-unsafe-swiftshader \
    --disable-features=Translate,msEdgeTranslate,CalculateNativeWinOcclusion,WebContentsOcclusion \
    --disable-backgrounding-occluded-windows \
    --disable-renderer-backgrounding \
    --disable-background-timer-throttling \
    --deny-permission-prompts \
    --autoplay-policy=no-user-gesture-required \
    --remote-debugging-port=9334 --remote-debugging-address=127.0.0.1 \
    --user-data-dir="$PROFILE" \
    --no-first-run --no-default-browser-check --hide-crash-restore-bubble \
    "$URL" </dev/null >/tmp/chrome-endfield.log 2>&1 &
  sleep 16
}

# 读 CDP 报的视口尺寸；sway 输出尚未应用时 Chrome 不会全屏，视口会偏小（曾见 1248x591），
# 那样所有 ROI/模板坐标整体偏移，识别必然失败。启动后必须校验。
# 注意：Chrome 启动瞬间 kiosk 尚未生效，视口会是 1248x591（含窗口 UI）。必须等页面
# readyState=complete 且 URL 已到 endfield 再读，否则会误判并白白重启 Chrome。
check_viewport() {
  python3 - <<'PY'
import json
import time
import urllib.request

try:
    import websocket
except ImportError:
    print("?"); raise SystemExit

deadline = time.time() + 40
last = "?"
while time.time() < deadline:
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:9334/json", timeout=5))
        pages = [t for t in d if t["type"] == "page"]
        if not pages:
            time.sleep(2); continue
        ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=8, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression":
                                       'JSON.stringify({rs:document.readyState,href:location.href,'
                                       'vp:[innerWidth,innerHeight].join("x")})',
                                       "returnByValue": True}}))
        val = None
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == 1:
                val = r.get("result", {}).get("result", {}).get("value")
                break
        ws.close()
        if val:
            st = json.loads(val)
            last = st.get("vp", "?")
            if st.get("rs") == "complete" and "endfield" in (st.get("href") or ""):
                print(last); raise SystemExit
    except SystemExit:
        raise
    except Exception:
        pass
    time.sleep(2)
print(last)
PY
}

echo "[i] 起 Chrome: $CHROME"
launch_chrome

WANT_VP="${CHROME_WIN/,/x}"
for attempt in 1 2 3 4; do
  GOT_VP="$(check_viewport)"
  if [ "$GOT_VP" = "$WANT_VP" ]; then
    echo "[i] 视口 ${GOT_VP} 正常"
    break
  fi
  echo "[warn] 视口 ${GOT_VP} ≠ ${WANT_VP}，等 5s 复查" >&2
  sleep 5
  GOT_VP="$(check_viewport)"
  if [ "$GOT_VP" = "$WANT_VP" ]; then
    echo "[i] 复查后视口 ${GOT_VP} 正常"
    break
  fi
  echo "[warn] 复查仍为 ${GOT_VP}，重启 Chrome（第 ${attempt} 次）" >&2
  if [ "$attempt" -ge 4 ]; then
    echo "[!] 视口连续 4 次不符，中止（sway 输出可能未就绪）" >&2
    exit 3
  fi
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null
  sleep 3
  rm -f "$PROFILE"/SingletonLock "$PROFILE"/SingletonCookie "$PROFILE"/SingletonSocket "$PROFILE"/lockfile 2>/dev/null
  launch_chrome
done

# 隐藏云端悬浮球：它浮在 canvas 上、默认停在左上角，会遮住游戏标题区（OCR/模板都会受它影响）。
# 脚本对当前页面立即生效，并注册到之后的每次页面加载。
HIDE_PY="$(dirname "$0")/../overlay_ctl.py"
[ -f "$HIDE_PY" ] || HIDE_PY="$(dirname "$0")/hide_cloud_overlay.py.bak-20261102"
[ -f "$HIDE_PY" ] || HIDE_PY="$(dirname "$0")/hide_cloud_ball.py"
if [ -f "$HIDE_PY" ]; then
  pkill -f "hide_cloud_ball.py --watch" 2>/dev/null
  pkill -f "hide_cloud_overlay.py --watch" 2>/dev/null
  pkill -f "overlay_ctl.py --watch" 2>/dev/null
  setsid python3 "$HIDE_PY" --watch </dev/null >/tmp/hermes-hide-overlay.log 2>&1 &
fi

echo "  socket: $RUNTIME/wayland-1"
echo "  进程: $(ps -eo args | grep -c '[e]ndfield-web')"

curl -s --max-time 5 http://127.0.0.1:9334/json/version | head -2
