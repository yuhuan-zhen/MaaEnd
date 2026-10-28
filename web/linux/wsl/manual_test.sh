#!/usr/bin/env bash
# 手动分阶段测试（在 WSL / Linux 上跑）。一次只做一件事，跑完自己收尾。
#
#   ./manual_test.sh host     # ① 不用账号：起浏览器 → 验注入/状态/视口 → 截图
#   ./manual_test.sh login    # ② 真页面：截图二维码到 Windows，你扫码，等到进游戏
#   ./manual_test.sh daily    # ③ 跑一轮日常（默认 --only 3,4,5，可加 --ladder L0..L3）
#   ./manual_test.sh status   # 看当前状态
#   ./manual_test.sh stop     # 收尾：关浏览器 + sway
#
# 常用环境变量（都有默认值）：
#   REPO=/mnt/d/maaend-upstream
#   LAUNCHER=/mnt/d/UserDocuments/MaaEnd-review/launcher-draft/cloud-web-launch/cloud-web-launch-linux
#   DIST=/root/maaend
#   MODE=compositor|headless        （默认 compositor，给框架内置 Linux 控制器用）
#   PORT=9334                        （CDP 端口，自用驱动默认连这个）
#   URL=https://endfield.hypergryph.com/cloud
set -uo pipefail

REPO="${REPO:-/mnt/d/maaend-upstream}"
WEB="$REPO/web"
LAUNCHER="${LAUNCHER:-/mnt/d/UserDocuments/MaaEnd-review/launcher-draft/cloud-web-launch/cloud-web-launch-linux}"
DIST="${DIST:-/root/maaend}"
MODE="${MODE:-compositor}"
PORT="${PORT:-9334}"
URL="${URL:-https://endfield.hypergryph.com/cloud}"
STATE_DIR=/tmp/maaend-manual
LAUNCH_JSON="$STATE_DIR/launch.json"
LOG="$STATE_DIR/launcher.log"
SHOT_DIR="${SHOT_DIR:-/mnt/d/桌面/maaend-manual}"

# 代理：WSL 直连 web.hycdn.cn 只有 ~11 KB/s，账号 SDK（134 KB）要 12 秒，
# 超过 SDK 自己的初始化超时 → 页面永远停在“页面启动未完成”。
# 走宿主机上的代理（一般是 mihomo/clash 的 7890）能到 ~660 KB/s。
wsl_gateway() {
  python3 - <<'PY' 2>/dev/null
import socket, struct
for line in open("/proc/net/route").read().splitlines()[1:]:
    f = line.split()
    if f[1] == "00000000":
        print(socket.inet_ntoa(struct.pack("<L", int(f[2], 16))))
        break
PY
}
if [ -z "${MAAEND_WEB_PROXY:-}" ]; then
  GW=$(wsl_gateway)
  if [ -n "$GW" ]; then
    # 只有代理真的能通才用，避免设置不通的代理反而更慢
    if curl -s -o /dev/null -m 3 -x "http://$GW:7890" https://web.hycdn.cn/ ; then
      MAAEND_WEB_PROXY="http://$GW:7890"
    fi
  fi
fi
export MAAEND_WEB_PROXY

stage="${1:-}"; shift || true
ONLY="3,4,5"; LADDER="L3"
# compositor 模式默认走框架内置 Linux 控制器（与 MXU 一致）；headless 只能用 cdp
if [ "$MODE" = "compositor" ]; then CONTROLLER="wlroots"; else CONTROLLER="cdp"; fi
while [ $# -gt 0 ]; do
  case "$1" in
    --only) ONLY="$2"; shift 2 ;;
    --ladder) LADDER="$2"; shift 2 ;;
    --controller) CONTROLLER="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

mkdir -p "$STATE_DIR" "$SHOT_DIR"

info()  { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()   { printf '  \033[31m✗\033[0m %s\n' "$*"; }
need()  { command -v "$1" >/dev/null || { bad "缺少 $1"; exit 1; }; }

launcher_pid() {
  [ -f "$LAUNCH_JSON" ] || return 1
  python3 - "$LAUNCH_JSON" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["pid"])
PY
}

wait_launch_json() {
  local i
  for i in $(seq 1 90); do
    [ -s "$LAUNCH_JSON" ] && return 0
    sleep 1
  done
  return 1
}

do_stop() {
  info "收尾"
  if [ -f "$LAUNCH_JSON" ]; then
    local ctl
    ctl=$(python3 - "$LAUNCH_JSON" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["control"])
PY
)
    "$LAUNCHER" --stop --addr "$ctl" 2>/dev/null || true
    ok "已请求 launcher 退出（$ctl）"
  fi
  pkill -f "user-data-dir=$STATE_DIR/profile" 2>/dev/null || true
  pkill -x sway 2>/dev/null || true
  rm -f "$LAUNCH_JSON"
}

do_start() {
  local url="$1"
  do_stop >/dev/null 2>&1
  rm -f "$LAUNCH_JSON" "$LOG"
  info "起 launcher（mode=$MODE, port=$PORT）"
  nohup "$LAUNCHER" --prepare --mode "$MODE" --cdp-port "$PORT" \
        --profile "$STATE_DIR/profile" --url "$url" \
        > "$LAUNCH_JSON" 2> "$LOG" &
  if ! wait_launch_json; then
    bad "launcher 没输出 ready JSON，看 $LOG"
    tail -20 "$LOG" || true
    exit 1
  fi
  ok "$(cat "$LAUNCH_JSON")"
}

case "$stage" in
  host)
    need python3
    [ -x "$LAUNCHER" ] || { bad "找不到 launcher: $LAUNCHER（先在 Windows 上 GOOS=linux go build）"; exit 1; }
    do_start "file://$WEB/linux/tests/fake_cloud_page.html"
    info "体检：状态 / 注入 / 视口"
    python3 "$WEB/linux/wsl/attach_probe.py" --json "$LAUNCH_JSON" \
            --shot "$SHOT_DIR/host.png"
    ok "截图: $SHOT_DIR/host.png"
    ;;

  login)
    do_start "$URL"
    info "等页面出来，截一张二维码"
    python3 "$WEB/linux/wsl/attach_probe.py" --json "$LAUNCH_JSON" \
            --shot "$SHOT_DIR/login.png" --quiet || true
    ok "截图: $SHOT_DIR/login.png"
    echo
    echo "  用手机扫这张图里的二维码登录；登录后会自动继续到进游戏。"
    echo "  下面最多等 300 秒（Ctrl-C 可中断，浏览器不会关）："
    python3 "$WEB/linux/wsl/attach_probe.py" --json "$LAUNCH_JSON" \
            --shot "$SHOT_DIR/ready.png" --wait-ready 300
    ;;

  wlr)
    [ -f "$LAUNCH_JSON" ] || { bad "先起浏览器：./manual_test.sh host 或 login"; exit 1; }
    SOCK=$(python3 - "$LAUNCH_JSON" <<'PY'
import json,sys
print(json.load(open(sys.argv[1])).get("wlr") or "")
PY
)
    if [ -z "$SOCK" ]; then bad "launcher 不是 compositor 模式（没有 wlr 字段）"; exit 1; fi
    info "用框架内置 Linux 控制器连一次（sock=$SOCK）"
    python3 "$WEB/linux/wsl/wlr_probe.py" --sock "$SOCK" --shot "$SHOT_DIR/wlr.png"
    ok "截图: $SHOT_DIR/wlr.png"
    ;;

  daily)
    [ -f "$LAUNCH_JSON" ] || { bad "先跑 ./manual_test.sh login，浏览器还没起"; exit 1; }
    BASE="$DIST/resource"
    MIN="$WEB/linux/resource_web_min"
    STRUCT="$WEB/linux/resource_web_structural"
    START="$WEB/linux/resource_web_startup"
    [ -d "$MIN" ] || { info "先生成分层"; python3 "$WEB/linux/split_overlay.py" --write; }
    case "$LADDER" in
      L0) DIRS="$BASE" ;;
      L1) DIRS="$BASE:$MIN" ;;
      L2) DIRS="$BASE:$MIN:$STRUCT" ;;
      L3) DIRS="$BASE:$MIN:$STRUCT:$START:$WEB/linux/resource_web_linux" ;;
      *)  bad "未知 --ladder $LADDER（L0/L1/L2/L3）"; exit 2 ;;
    esac
    info "跑一轮：controller=$CONTROLLER only=$ONLY ladder=$LADDER"
    echo "  资源: $DIRS"
    # shellcheck disable=SC2086
    MAAEND_DIST="$DIST" MAAEND_WEB="$WEB" MAAEND_RES_DIRS="$DIRS" \
      python3 "$WEB/linux/run_daily_linux.py" --controller "$CONTROLLER" \
              --only "$ONLY" ${EXTRA_ARGS:-}
    ;;

  status)
    if [ -f "$LAUNCH_JSON" ]; then cat "$LAUNCH_JSON"; else echo "没有在跑的实例"; fi
    pgrep -a sway | head -3
    pgrep -c chrome || true
    ;;

  stop) do_stop ;;

  *)
    sed -n '2,20p' "$0"
    exit 1
    ;;
esac
