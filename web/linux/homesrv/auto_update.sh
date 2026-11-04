#!/usr/bin/env bash
# 每天定时运行前：检查 MaaEnd 最新发行版 -> 有更新则 备份/替换/叠回覆盖层/自检 -> 清理旧备份（保留最近 4 份）
#
# 设计要点：
#   * 只在版本变化时才下载（400MB 级），不变化直接退出，几乎不耗时。
#   * 备份与替换都不碰 web/ 与 config/ —— 我们的网页端覆盖层、脚本、预设都在那里。
#   * 发行版会整包覆盖 tasks/ 与 resource/：装完必须把「仓库侧覆盖层」叠回（遗留 5）——
#     tasks 文件、interface.json 的 import、发行版 pipeline 的定点修补，内容与顺序由同目录
#     overlay_ops.json 声明、overlay_apply.py 执行。叠回失败 = 回滚 + 写 upgrade_alert.txt + 响铃。
#   * 替换后跑 post_upgrade_check.py（15 个关键节点必须在位），失败自动回滚到刚备份的版本。
#   * 任何异常都以"保持当前版本"收场，绝不让更新把日常跑挂；退出码恒 0（与重构前一致）。
#     失败信号 = upgrade.log 里的 [!] 行 + upgrade_alert.txt（nightly 会亮出来）+ 响铃。
#
# 用法: auto_update.sh [--check] [--force]
#   --check  只看版本，不动任何文件
#   --force  版本相同也重装一次
#
# 环境变量：
#   MAAEND_DIST / MAAEND_ROOT  部署目录，默认 ~/maaend
#   MAAEND_PROXY               下载代理，默认 http://127.0.0.1:7890；设成空串 = 直连
#   MAAEND_KEEP_BACKUPS        保留几份旧备份，默认 4
set -uo pipefail

ROOT="${MAAEND_DIST:-${MAAEND_ROOT:-$HOME/maaend}}"
WEB="$ROOT/web"
BK="$ROOT/backups"
STATE="$ROOT/upgrade_state.json"
LOG="$ROOT/upgrade.log"
ALERT="$ROOT/upgrade_alert.txt"
PROXY="${MAAEND_PROXY-http://127.0.0.1:7890}"
KEEP="${MAAEND_KEEP_BACKUPS:-4}"
CHECK_PY="$WEB/linux/homesrv/post_upgrade_check.py"
AUDIT_PY="$WEB/linux/homesrv/option_audit.py"
OVERLAY_PY="$WEB/linux/homesrv/overlay_apply.py"

MODE_CHECK=0
MODE_FORCE=0
for a in "$@"; do
  [ "$a" = "--check" ] && MODE_CHECK=1
  [ "$a" = "--force" ] && MODE_FORCE=1
done

log() { echo "[$(date -Is)] $*" >>"$LOG"; }

# 失败告警：写日志 + 覆盖 upgrade_alert.txt（nightly 开跑时先读它）+ 终端响铃。
# cron 把 stderr 丢掉了，所以别指望那一声铃；文件与日志才是真正能被人看到的信号。
alert() {
  local msg="$*"
  log "[!] $msg"
  printf '%s %s\n' "$(date -Is)" "$msg" >"$ALERT"
  printf '\a[!] %s\n' "$msg" >&2
}

clear_alert() {
  rm -f "$ALERT"
}

# 统一的 curl 取件：跟随重定向；PROXY 非空才带 -x（空串 = 直连）。
curl_get() { # <url> <out> <max-time>
  if [ -n "$PROXY" ]; then
    curl -sL -x "$PROXY" --max-time "$3" -o "$2" "$1"
  else
    curl -sL --max-time "$3" -o "$2" "$1"
  fi
}

# 覆盖项基线检查：上游改了选项树（加深层级/新增 input 型/改类型）时当天可见。
# 失败会写 $ROOT/option_drift.json，供日报/下次开跑时读取。
run_audit() {
  [ -f "$AUDIT_PY" ] || return 0
  if (cd "$ROOT" && MAAEND_ROOT="$ROOT" timeout 180 python3 "$AUDIT_PY" --check \
        --json-out "$ROOT/option_drift.json" >>"$LOG" 2>&1); then
    rm -f "$ROOT/option_drift.json"
    log "覆盖项基线正常"
    return 0
  fi
  log "覆盖项基线异常（疑似上游改了选项树，详见 $ROOT/option_drift.json）"
  return 1
}

# 把仓库侧覆盖层叠回部署树（tasks + interface import + 发行版 pipeline 修补）。
# 幂等：每晚都跑，已叠回的只报「无需改动」。
apply_overlay() {
  if [ ! -f "$OVERLAY_PY" ]; then
    alert "叠回覆盖层失败：缺 $OVERLAY_PY（部署不完整，先跑 homesrv/deploy.sh）"
    return 1
  fi
  log "---- 叠回覆盖层 ----"
  if (cd "$ROOT" && MAAEND_DIST="$ROOT" python3 "$OVERLAY_PY" --root "$ROOT" --src "$ROOT" >>"$LOG" 2>&1); then
    log "覆盖层已叠回（tasks / interface import / pipeline 修补）"
    return 0
  fi
  alert "叠回覆盖层失败（详见 $LOG 末尾），回滚到升级前版本"
  return 1
}

cur_version() {
  python3 - "$ROOT/interface.json" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8-sig'))
    print(d.get('version') or 'unknown')
except Exception:
    print('unknown')
PY
}

# 只留最近 KEEP 份备份（按 mtime 排序，不看文件名）。
prune_backups() {
  local d line rows=()
  for d in "$BK"/*/; do
    [ -d "$d" ] || continue
    rows+=("$(stat -c %Y "$d" 2>/dev/null || echo 0) $d")
  done
  if [ "${#rows[@]}" -le "$KEEP" ]; then
    return 0
  fi
  printf '%s\n' "${rows[@]}" | sort -rn | tail -n +$((KEEP + 1)) | while IFS= read -r line; do
    d="${line#* }"
    [ -n "$d" ] || continue
    rm -rf "$d"
    log "清理旧备份 $(basename "$d")"
  done
  return 0
}

CUR=$(cur_version)
log "---- 检查开始（当前 $CUR）----"

# 有任务在跑就不动，避免替换到一半被使用
if pgrep -f "run_daily_linux[.]py" >/dev/null 2>&1; then
  log "有任务正在运行，跳过本次更新"
  exit 0
fi

# 1) 查最新 release（含 prerelease，按发布时间取最新）
TMPJ=$(mktemp /tmp/maaend-rel-XXXXXX.json)
curl_get "https://api.github.com/repos/MaaEnd/MaaEnd/releases?per_page=10" "$TMPJ" 40 2>/dev/null
# 注意：不能写成 `printf ... | python3 - <<'PY'`——heredoc 会顶掉管道，脚本读到的不是 JSON
PARSED=$(python3 - "$TMPJ" <<'PY' 2>/dev/null
import json, sys
try:
    rels = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print(''); raise SystemExit
rels = [r for r in rels if not r.get('draft')]
if not rels:
    print(''); raise SystemExit
rels.sort(key=lambda r: r.get('published_at') or '', reverse=True)
r = rels[0]
url = ''
for a in r.get('assets') or []:
    n = a.get('name') or ''
    if n.startswith('MaaEnd-linux-x86_64-') and n.endswith('.tar.gz'):
        url = a.get('browser_download_url') or ''
        break
print('%s|%s|%s' % (r.get('tag_name', ''), (r.get('published_at') or '')[:19], url))
PY
)
rm -f "$TMPJ"

# GitHub API 常因共享出口 IP 被限流（403 rate limit），此时回退到 releases.atom：
# 该源无速率限制，且 Linux 包名可预测 -> MaaEnd-linux-x86_64-<tag>.tar.gz
if [ -z "$PARSED" ] || [ -z "${PARSED##*|}" ]; then
  ATOMJ=$(mktemp /tmp/maaend-atom-XXXXXX.xml)
  curl_get "https://github.com/MaaEnd/MaaEnd/releases.atom" "$ATOMJ" 40 2>/dev/null
  PARSED=$(python3 - "$ATOMJ" <<'PY' 2>/dev/null
import re, sys
try:
    s = open(sys.argv[1], encoding='utf-8').read()
except Exception:
    print(''); raise SystemExit
blocks = re.findall(r'<entry>(.*?)</entry>', s, re.S)
if not blocks:
    print(''); raise SystemExit
entry = blocks[0]
mt = re.search(r'<title>([^<]+)</title>', entry)
mu = re.search(r'<updated>([^<]+)</updated>', entry)
if not mt:
    print(''); raise SystemExit
tag = mt.group(1).strip()
if not re.match(r'^v\d+\.', tag):
    print(''); raise SystemExit
pub = mu.group(1)[:19] if mu else ''
print('%s|%s|https://github.com/MaaEnd/MaaEnd/releases/download/%s/MaaEnd-linux-x86_64-%s.tar.gz'
      % (tag, pub, tag, tag))
PY
  )
  rm -f "$ATOMJ"
  [ -n "$PARSED" ] && log "API 不可用或缺少 Linux 资产，已回退 releases.atom"
fi

TAG=${PARSED%%|*}
REST=${PARSED#*|}
PUB=${REST%%|*}
URL=${REST#*|}

if [ -z "${TAG:-}" ] || [ -z "${URL:-}" ]; then
  log "取最新版本失败（网络/接口），保持当前 $CUR"
  exit 0
fi
log "上游最新: $TAG ($PUB)"

if [ "$MODE_CHECK" = "1" ]; then
  echo "当前: $CUR"
  echo "最新: $TAG ($PUB)"
  echo "包:   $URL"
  exit 0
fi

if [ "$TAG" = "$CUR" ] && [ "$MODE_FORCE" != "1" ]; then
  log "已是最新（$CUR），无需更新"
  # 不升级的日子也要检查一次基线（约 3 秒），否则告警只在升级当天出现
  run_audit || true
  # 顺手补一次叠回：deploy.sh 换过代码、清过 import 时也能自愈（幂等，几毫秒）
  apply_overlay || true
  exit 0
fi

FREE_KB=$(df -Pk "$ROOT" | awk 'NR==2{print $4}')
if [ "${FREE_KB:-0}" -lt 2097152 ]; then
  log "磁盘不足 2GB（${FREE_KB}KB），跳过更新"
  exit 0
fi

TS=$(date +%Y%m%d-%H%M%S)
DEST="$BK/$TS"
mkdir -p "$DEST" "$BK" || { log "建备份目录失败"; exit 0; }

rollback() {
  log "!! 回滚到 $CUR"
  rm -rf "$ROOT/resource" "$ROOT/maafw"
  [ -d "$DEST/resource" ] && mv "$DEST/resource" "$ROOT/resource"
  [ -d "$DEST/maafw" ] && mv "$DEST/maafw" "$ROOT/maafw"
  [ -f "$DEST/interface.json" ] && cp -a "$DEST/interface.json" "$ROOT/interface.json"
  [ -d "$DEST/agent" ] && cp -a "$DEST/agent/." "$ROOT/agent/" 2>/dev/null
  # tasks 也要还原：发行版覆盖过 tasks/，叠回失败时不能留下半新半旧的清单
  if [ -d "$DEST/tasks" ]; then
    rm -rf "$ROOT/tasks"
    cp -a "$DEST/tasks" "$ROOT/tasks"
  fi
  ln -sfn "$ROOT/maafw" "$ROOT/agent/maafw"
  log "已回滚；当前版本 $(cur_version)"
}

echo "$CUR" >"$DEST/VERSION"

# 2) 备份当前：直接 mv（快，也保证备份是完整的）；tasks 用 cp（5MB 级，回滚要能整目录还原）
[ -d "$ROOT/resource" ] && mv "$ROOT/resource" "$DEST/resource"
cp -a "$ROOT/interface.json" "$DEST/interface.json" 2>/dev/null
mkdir -p "$DEST/agent"
mv "$ROOT/agent/go-service" "$DEST/agent/" 2>/dev/null
mv "$ROOT/agent/cpp-algo" "$DEST/agent/" 2>/dev/null
[ -d "$ROOT/maafw" ] && mv "$ROOT/maafw" "$DEST/maafw"
[ -d "$ROOT/tasks" ] && cp -a "$ROOT/tasks" "$DEST/tasks"
log "已备份到 $DEST"

# 3) 下载 + 解包
TMP=$(mktemp -d /tmp/maaend-up-XXXXXX)
if ! curl_get "$URL" "$TMP/pkg.tar.gz" 1800; then
  log "下载失败"
  rollback
  rm -rf "$TMP"
  exit 0
fi
if ! tar xzf "$TMP/pkg.tar.gz" -C "$TMP" 2>/dev/null; then
  log "解包失败"
  rollback
  rm -rf "$TMP"
  exit 0
fi
SRC="$TMP"
[ -d "$TMP/x" ] && SRC="$TMP/x"

if [ ! -f "$SRC/resource/pipeline/nodes.json" ] || [ ! -f "$SRC/interface.json" ]; then
  log "包内容不完整"
  rollback
  rm -rf "$TMP"
  exit 0
fi

# 4) 替换（只换 resource / interface / agent 二进制 / maafw / tasks）
cp -a "$SRC/resource" "$ROOT/resource" || { log "拷贝 resource 失败"; rollback; rm -rf "$TMP"; exit 0; }
cp -a "$SRC/interface.json" "$ROOT/interface.json" || { log "拷贝 interface 失败"; rollback; rm -rf "$TMP"; exit 0; }
# tasks/ 也要一起换：interface.json 每次都会更新，而它 import 的任务清单跟着变
# （v2.35 新增 LaunchGameLinux / pretasks/LaunchGamePC，不同步就会「任务不存在于接口」）。
# 只覆盖同名文件，不删除本地自建任务；我们的 tasks 由下面的 apply_overlay 叠回。
if [ -d "$SRC/tasks" ]; then
  mkdir -p "$ROOT/tasks"
  cp -a "$SRC/tasks/." "$ROOT/tasks/" || { log "拷贝 tasks 失败"; rollback; rm -rf "$TMP"; exit 0; }
  log "已同步 tasks/"
fi

if [ -f "$SRC/agent/go-service" ]; then
  cp -a "$SRC/agent/go-service" "$ROOT/agent/go-service"
  cp -a "$SRC/agent/cpp-algo" "$ROOT/agent/cpp-algo" 2>/dev/null
  chmod +x "$ROOT/agent/go-service" "$ROOT/agent/cpp-algo" 2>/dev/null
fi
[ -d "$SRC/maafw" ] && cp -a "$SRC/maafw" "$ROOT/maafw"
ln -sfn "$ROOT/maafw" "$ROOT/agent/maafw"
rm -rf "$TMP"
log "已替换为 $TAG"

# 补丁（cpp-algo 必须停在 1.0856 版）：11-02 23:53 的包自带 compute_view_units_per_degree，
# 在 1280x720 云网页端算出 7.93 units/度，而 10-27 三档实测是 3.86 —— 2 倍超调会让导航永不收敛。
WANT_MD5=4056272952b61fe10a9e0a0e7484bbf5
GOT_MD5=$(md5sum "$ROOT/agent/cpp-algo" 2>/dev/null | cut -d' ' -f1)
if [ "$GOT_MD5" != "$WANT_MD5" ]; then
  PATCH_BIN="$ROOT/patches/agent/cpp-algo-1.0856.bin"
  [ -f "$PATCH_BIN" ] || PATCH_BIN="$ROOT/agent/cpp-algo.bak-20261027-162613"
  if [ -f "$PATCH_BIN" ]; then
    cp -a "$ROOT/agent/cpp-algo" "$ROOT/agent/cpp-algo.bak-auto-$(date +%Y%m%d-%H%M)"
    cp -a "$PATCH_BIN" "$ROOT/agent/cpp-algo"
    chmod +x "$ROOT/agent/cpp-algo"
    log "补丁：cpp-algo 已换回 1.0856 版（3.86 units/度），被换掉的 md5=$GOT_MD5"
  else
    alert "补丁：cpp-algo 需要回退但找不到 1.0856 备份（导航可能 2 倍超调）"
  fi
else
  log "补丁：cpp-algo md5 已是 1.0856 版"
fi

# 5) 叠回仓库侧覆盖层（遗留 5）：发行版刚把 tasks/interface/resource 覆盖掉，这里按
#    overlay_ops.json 把我们的 tasks、import 与 pipeline 修补重新压上去。失败即回滚。
if ! apply_overlay; then
  rollback
  exit 0
fi

# 6) 自检：15 个关键节点必须都在（覆盖层 + base）
if [ -f "$CHECK_PY" ]; then
  if ! (cd "$ROOT" && timeout 180 python3 "$CHECK_PY" >>"$LOG" 2>&1); then
    log "自检未通过，回滚"
    rollback
    exit 0
  fi
  log "自检通过"
else
  alert "缺少自检脚本 $CHECK_PY（跳过自检，升级结果未验证）"
fi

# 6b) 覆盖项基线：放在自检之外——回滚后的运行时同样值得对照基线
AUDIT_FAILED=0
run_audit || AUDIT_FAILED=1

# 7) 只留最近 KEEP 份备份
prune_backups

mkdir -p "$BK"
python3 - "$TAG" "$PUB" <<'PY' >"$STATE" 2>/dev/null
import json, sys, time
print(json.dumps({'version': sys.argv[1], 'published_at': sys.argv[2],
                  'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False))
PY
if [ "$AUDIT_FAILED" = "1" ]; then
  alert "完成 $CUR -> $TAG，但覆盖项基线异常（见 option_drift.json）"
else
  log "完成：$CUR -> $TAG"
fi
# 升级+叠回都成功：清掉历史告警，nightly 不再反复亮旧消息
if [ "$AUDIT_FAILED" != "1" ]; then
  clear_alert
fi
exit 0
