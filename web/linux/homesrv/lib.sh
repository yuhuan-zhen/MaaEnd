#!/usr/bin/env bash
# homesrv 部署脚本公共层：cron 会话变量、路径推导、日志轮转、浏览器启动、页面归位、浮层自检、收尾。
# 只定义函数，顶层不执行任何动作，由 daily / essence / nightly 三个入口 source。
# 调用方各自保留 set -uo pipefail，以及 CONF / TASKS / 实例 / 退出码这些真正的差异。
# 顺序：会话 → 轮转 → 收尾 → 启动 → 等 CDP → 归位 → 浮层 → 入口 mh_init（放最后，读起来是总装）。

# cron 环境下补齐会话变量（缺 XDG_RUNTIME_DIR 会让点击不生效）。
# 手动跑时这些变量已在环境里，保持原值不动。
mh_session() {
  if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "/run/user/$(id -u)" ]; then
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export XDG_RUNTIME_DIR
  fi
  if [ -z "${XDG_SESSION_TYPE:-}" ]; then
    export XDG_SESSION_TYPE=wayland
  fi
  if [ -S "${XDG_RUNTIME_DIR:-/nonexistent}/bus" ]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
  fi
  return 0
}

# 日志轮转：只保留最近 3 次运行（xxx.log + .1 + .2）。
mh_rotate_log() {
  local logfile="$1"
  if [ -s "$logfile" ]; then
    rm -f "$logfile.2"
    if [ -f "$logfile.1" ]; then
      mv -f "$logfile.1" "$logfile.2"
    fi
    mv -f "$logfile" "$logfile.1"
  fi
  return 0
}

# 收尾：先通知服务端结束会话，再关 Chrome / agent / 浮层 / 合成器，最后打印三项残留计数。
# 用 mh_init 注册到 EXIT INT TERM，失败与中断也照样清理。
mh_cleanup() {
  echo "[i] 收尾：先让页面离开云游戏（通知服务端结束会话），再关进程"
  python3 "$WEB/linux/leave_game.py" --port 9334 2>&1 | tail -2 || true
  echo "[i] 收尾：关闭 云·终末地 与 MaaEnd 相关进程"
  pkill -f "run_daily_linux.py" 2>/dev/null
  pkill -f "$ROOT/agent/go-service" 2>/dev/null
  pkill -f "hide_cloud_ball.py --watch" 2>/dev/null
  pkill -f "hide_cloud_overlay.py --watch" 2>/dev/null
  pkill -f "overlay_ctl.py --watch" 2>/dev/null
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null
  sleep 2
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null
  pkill -x swaybg 2>/dev/null
  pkill -x sway 2>/dev/null
  sleep 1
  local left_chrome left_agent left_sway
  left_chrome=$(pgrep -fc "google-chrome.*user-data-dir=$PROFILE" 2>/dev/null || true)
  left_agent=$(pgrep -fc "$ROOT/agent/go-service" 2>/dev/null || true)
  left_sway=$(pgrep -fc "sway -c " 2>/dev/null || true)
  left_chrome=${left_chrome:-0}
  left_agent=${left_agent:-0}
  left_sway=${left_sway:-0}
  echo "[i] 残留：chrome=$left_chrome agent=$left_agent sway=$left_sway"
  return 0
}

# 起 sway + Chrome（唯一启动入口是 chrome_homesrv.sh，含视口校验与浮层注入）。
# 失败统一返回 10，调用方用 `mh_start_chrome || exit 10`。
mh_start_chrome() {
  if ! bash "$WEB/linux/homesrv/chrome_homesrv.sh"; then
    echo "[X] 启动浏览器失败"
    return 10
  fi
  return 0
}

# 等 CDP 端点起来：最多 30 次 × 2s（与重构前一致，超时不报错，交给后面步骤暴露）。
mh_wait_cdp() {
  local i
  for ((i = 1; i <= 30; i++)); do
    if curl -s --max-time 2 http://127.0.0.1:9334/json/version >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  return 0
}

# 回到启动页并滚到顶，避免上次点击把页面带偏；归位失败不阻塞后续任务。
mh_reset_page() {
  python3 "$WEB/linux/reset_page.py" --port 9334 --url https://endfield.hypergryph.com/cloud --wait 12 2>&1 | tail -2
  return 0
}

# 验证悬浮球与延迟角标是否被隐藏（overlay_ctl.py 在 chrome 启动时注入）。
mh_overlay_check() {
  if [ -f "$WEB/linux/overlay_ctl.py" ]; then
    python3 "$WEB/linux/overlay_ctl.py" --check 2>&1 | sed 's/^/[浮层] /'
  fi
  return 0
}

# 入口：mh_init <root> <logfile>。
# 推导 WEB / CONF（由 logfile 主名得到，daily.log → daily.conf）/ PROFILE，导出 MAAEND_*，
# 轮转日志、接管 stdout/stderr、注册收尾 trap。
# ROOT/WEB/CONF/LOG/PROFILE 故意保持全局：脚本主体与子进程都要读。
mh_init() {
  if [ $# -lt 2 ]; then
    echo "用法: mh_init <root> <logfile>" >&2
    return 2
  fi
  ROOT="$1"
  LOG="$2"
  WEB="$ROOT/web"
  # CONF 供调用方（daily/essence）source，本文件不读它，故此处只看不用
  # shellcheck disable=SC2034
  CONF="$ROOT/$(basename "$LOG" .log).conf"
  PROFILE="${MAAEND_PROFILE:-$HOME/.config/endfield-web}"

  mh_session
  export MAAEND_DIST="$ROOT"
  export MAAEND_ROOT="$ROOT"
  export MAAEND_WEB="$WEB"
  export MAAEND_RES_DIRS="$ROOT/resource:$ROOT/web/resource_web:$ROOT/web/linux/resource_web_linux:$ROOT/web/resource_web_homesrv"
  export MAA_AGENT_BIN="$ROOT/agent/go-service"
  export MAA_AGENT_LIB="$ROOT/maafw"

  mh_rotate_log "$LOG"
  : >"$LOG"
  exec >>"$LOG" 2>&1
  trap mh_cleanup EXIT INT TERM
  return 0
}
