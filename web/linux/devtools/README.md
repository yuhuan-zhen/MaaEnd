# devtools —— 非生产工具层

这里放**为了看清问题**的脚本：CDP 调试控制器、离线评分、模板重抠、WSL 实验环境。
它们不属于运行链路，删掉任何一个都不影响 `homesrv` 跑日常。

## 为什么要单独一层

技术选型镜像规则（`web/docs/project-20261104/PLAN.md` §2）：上游把取帧 / 输入注入 / 寻路 /
图像识别都放在 C++（MaaFramework `source/MaaLinuxControlUnit`、`agent/cpp-algo`），Python 只承担
开发工具与数据生成（`tools/**`）。因此：

- 生产链路只有一条：`web/linux/run_daily_linux.py`（+ `homesrv/*.sh`），帧与输入走框架的
  `Linux-Wlroots` 控制器；
- 凡是「用 Python 自己抓帧 / 自己点」的代码都只能是**对照物**，放在这里，并在文件头写明
  「非生产」；
- 生产侧唯一会碰 devtools 的地方是 `framework.make_controller("cdp")`——那是显式的调试开关
  （`--controller cdp`），默认不走。

## 内容

| 路径 | 作用 | 额外依赖 |
| --- | --- | --- |
| `cdp.py` | CDP 原生帧控制器（`<video>` 直读 + CDP 注入输入），用来量化合成器截图丢了多少锐度 | numpy、pillow、websocket-client |
| `hs_capture.py` | 按固定间隔抓 CDP 截图，事后定位「失败那一瞬间」 | websocket-client |
| `auto_dismiss_dialog.py` | 常驻接受 Chrome 原生对话框（`Leave site?`），WSL 手动测试用 | websocket-client |
| `enter_game.py` | 点「开始游戏」并等串流就绪（只读页面状态，不猜坐标） | websocket-client |
| `linux_probe.py` | 离线节点评分：给一张帧，用框架自己的识别器算命中/分数 | MaaFw、numpy、pillow |
| `wlr_smoke.py` | 控制器冒烟：连合成器 / 截一帧 / 点一下 | MaaFw、numpy、pillow |
| `recapture_template.py` | 从整帧裁新模板、落到覆盖层、当场自校验 | opencv、numpy |
| `calibrate_turn.py` | 转向灵敏度标定（拖拽 dx ↔ 角度），给转向常数定标 | MaaFw |
| `introspect_tasks.py` | 打印发行版 `interface.json` 导入的任务与选项默认值 | 无（标准库） |
| `wsl/` | WSL（Ubuntu-24.04）里的整套实验环境：起 sway/Chrome、扫码、分阶段手动测试 | 见 `wsl/README.md` |

每个脚本的头部 docstring 都写了 **背景 + 用法 + 退出码**；参数以 `--help` 为准。

## 规则

1. **不 import 生产包的私有实现**：只用 `maaend_web.config` / `maaend_web.page` /
   `maaend_web.page_control` / `maaend_web.overlay` 这些公开面。
2. **生产包不得依赖本层**（唯一例外见上：`--controller cdp`）。
3. 允许 numpy / pillow / opencv / websocket-client；生产运行期只允许标准库 + `maa`（+ 可选 PIL）。
4. 这里**不写** pipeline、资源、任务定义——要改识别就去 `assets/resource_cloud_web/`。
5. `wsl/` 是 root + Windows 盘符 + 代理的实验环境，路径默认值可用环境变量覆盖，不要拿去
   homesrv 上跑。
