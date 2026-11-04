"""浮层 CLI：只做 argparse，动作与退出码都在 :mod:`maaend_web.overlay`。

退出码（与上游 ``overlay_ctl.py`` 一致）：

===  ============================================================
0    全部已隐藏（--check）/ 注入成功（--once）/ 正常退出（--watch）
1    仍有可见浮层（--check）/ 有 target 注入失败（--once）
2    连不上 CDP、没有可用 target，或没给动作
===  ============================================================

``--ball-only`` 是 ``homesrv/hide_cloud_overlay.py`` 的旧参数：现在默认抹平就把悬浮球与
延迟角标一起藏（``page_js.FLATTEN_JS`` 的容器级规则），参数只为不打断老脚本而保留。
"""

from __future__ import annotations

import argparse

from .. import overlay


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="overlay",
        description="云网页端浮层控制（注入 page_js.FLATTEN_JS + cloud_policy_linux.js，用 PROBE_JS 探测）",
    )
    ap.add_argument("--devtools", default=overlay.DEVTOOLS_DEFAULT, help="CDP HTTP 端点，默认 %(default)s")
    ap.add_argument("--port", type=int, default=None, help="只给端口时等价于 http://127.0.0.1:<port>")
    ap.add_argument(
        "--url-hint",
        default=overlay.URL_HINT_DEFAULT,
        help="只处理 url 含该串的 page，默认 %(default)s",
    )
    ap.add_argument("--check", action="store_true", help="只探测并打印 JSON")
    ap.add_argument("--once", action="store_true", help="注入一次")
    ap.add_argument("--watch", action="store_true", help="常驻巡检（文档替换后自动重注入）")
    ap.add_argument("--interval", type=float, default=2.0, help="watch 轮询间隔秒，默认 %(default)s")
    ap.add_argument(
        "--probe-every",
        type=float,
        default=30.0,
        help="watch 里已注入 target 的探测间隔秒，默认 %(default)s",
    )
    ap.add_argument(
        "--no-policy",
        action="store_true",
        help="只注入抹平，不注入页面策略（cloud_policy_linux.js / page_js.INPUT_POLICY_JS）",
    )
    ap.add_argument(
        "--ball-only",
        action="store_true",
        help="兼容 hide_cloud_overlay.py 的旧参数；抹平默认连延迟角标一起藏，此参数不改变行为",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    devtools = f"http://127.0.0.1:{args.port}" if args.port else args.devtools
    if args.ball_only:
        print("（--ball-only：悬浮球与延迟角标现在一起隐藏，参数已无作用）", flush=True)
    if args.check:
        return overlay.run_check(devtools, args.url_hint)
    if args.watch:
        return overlay.run_watch(
            devtools,
            args.url_hint,
            args.interval,
            args.probe_every,
            policy=not args.no_policy,
        )
    if args.once:
        return overlay.run_once(devtools, args.url_hint, policy=not args.no_policy)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
