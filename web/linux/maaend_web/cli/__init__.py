"""``maaend_web`` 的命令行入口包。

每个子模块一个子命令：``daily``（日常编排，生产入口是 ``run_daily_linux.py``）、
``overlay``（浮层 CLI，生产入口是 ``overlay_ctl.py``）。顶层的旧脚本只做 import 转发，
命令行参数与退出码保持不变。

离线评分 / 转向标定这类开发工具不在这里，见 ``web/linux/devtools/``。
"""
