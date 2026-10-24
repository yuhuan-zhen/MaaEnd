# 交接 brief · pr6696 云网页转向/取帧测试

> 给下一个会话用的最小上下文。读完这一页，就不必回头翻 133 个文件或已压缩的对话历史。
> 生成于 2026-10-25。所有数值都可复现，命令在第六节。

## 一、这件事是什么

在 Linux 上跑云终末地网页版（WSL + sway + Chrome + CDP），用 MaaFramework 的
`CustomController` 截图与输入。围绕两个 PR 做实测：

- **#6696**（Linux 侧云网页参考实现，OPEN draft）——带了 `_MAX_RELATIVE_STEP = 127`
- **#6807**（提议框架内置 Web 控制器 + PI `type: "Web"`）——要把 `max_step: 127`
  和 `kDefaultTurnUnitsPerDegree = 4.0` 写成协议默认值

核心问题：**这两个常量原来没人验证过**。本测试线把它们全测了一遍。

## 二、已定结论（可直接引用，别再重测）

| # | 结论 | 数值 | 证据 |
| --- | --- | --- | --- |
| 1 | 云网页客户端灵敏度 | **4.0 units/度**（实测 3.99，95% CI [3.95, 4.03]） | `T5j-10轮统计.md` n=10 |
| 2 | 单次位移换算上限 | **≈126 units（≈32°）**，超出丢弃 | `T5i-灵敏度与上限实测.md` |
| 3 | 拆段可突破上限 | 360 一次 32.9° → 拆 3 段 94.0° | 同上 |
| 4 | 旧灵敏度（`delta×2`）误差 | 90° 命令只转 **45.48°**（名义 45°，即少一半） | `T5j-10轮统计.md` |
| 5 | 新灵敏度（×4） | **90.25°**（名义 90°），达成 100.3% | 同上 |
| 6 | 客户端驱动量 | **`movementX`**；固定锚点+覆写即可转，位置不动也行 | `T5j-修正生效补测.md` |
| 7 | 生产发法 vs 指针推进 | 等价，且生产更稳（sd 1.39 vs 4.94） | 同上 |
| 8 | 取帧延迟 720p 视频原生帧 JPEG q75 | **33.8 ms 单次 / 42.1 ms 稳态 → ~24 fps** | `T1b-取帧延迟实测.md` |
| 9 | 取帧延迟 720p `Page.captureScreenshot` JPEG | 84–92 ms → ~11 fps | 同上 |
| 10 | 取帧延迟 1080p 视频原生帧 JPEG | 84.1 ms → ~12 fps（切 1080p 后云客户端自动升流） | 同上 |
| 11 | 原始 RGBA base64 | 142.5 ms@720p（传输 118 ms 主导）→ **不要用** | 同上 |
| 12 | 箭头读取器精度 | 1.41° 中位（86 张带标注图） | `PLAN-朝向标定.md` |
| 13 | 箭头语义 | `rot` = **角色朝向**，与镜头无关 | `map-locator.md:41-43` + 实测 |
| 14 | 单腿指针行程上限 | 639 units（≈160°）@1280×720 | `T5f-8次90度失败记录.md` |

**已落地的改动**（分支 `feat/linux-adapt`，本地 fork）：

- `agent/go-service/common/charactercontroller/turn_sensitivity.go`（新增）
  按控制器类型取灵敏度：云网页 4.0 / 触摸 3.0 / 桌面 2.0；环境变量 `MAA_TURN_UNITS_PER_DEGREE` 可覆盖
- `controller.go` 的 yaw/pitch 动作改用该函数
- `cdp_controller.py` 的 `_MAX_RELATIVE_STEP = 127` 拆段逻辑**未改，保留**

## 三、已撤回的结论（最容易踩的坑）

| 旧说法 | 现状 |
| --- | --- |
| 「128–360 units 无截断，`max_step=127` 无必要性」（T5c） | **错**。存在约 126 units 硬上限，拆段才能突破 |
| 「一次 360 与 3×120 等效」（T5c） | 只在位置差总和意义成立；实际 32.9° vs 94.0° |
| 「客户端按指针位置差算旋转，不读 `movementX`」（T5g） | **错**。位置不动也能转（91.9°），驱动量就是 `movementX` |
| 「pointer lock 是绕过视口限制的解法」（T5g） | 能绕坐标限制，但**锁定后客户端不响应输入**，不是解法 |

T5g 当年的误判原因：pointer lock 下 `clientX` 冻结、旋转停止，把「锁定」误读成「位置差为零」。
T5c/T5d 的误判原因：用「画面差」当判据，而场景在动、噪声 7–27，32° 与 94° 分不开。

**方法上的教训**：判据必须对被测机制敏感。改用 `rot` 前后差（走一步法）后噪声降到 ±1°。

## 四、未解决（这是新会话该讨论的）

| # | 项 | 状态 | 难点 |
| --- | --- | --- | --- |
| 1 | 纵向（pitch）标定 | 未测 | 方法现成（抬头→走一步），`pitchUnitsPerDegree` 目前与水平共用属**未验证假设** |
| 2 | 目标角度 > 160° | 结构性阻塞 | 单腿 639 units；回位也受 126 上限，只能回 ~32°，**残留偏移** |
| 3 | 取帧+识别整链 | 未测 | T1b 只到「拿到 BGR ndarray」，识别耗时未含 |
| 4 | #6807 评论草稿 | 未写 | 结论已齐，缺一份可直接贴的稿子 |

## 五、边界（别越过）

- **不向上游提 PR**。改动机只留本地，历史上有一次误开 PR 被要求关闭
- **不改 Win32 的 2.0 / ADB 的 3.0**：那是各自独立标定，套 4.0 会把官方客户端改慢 4 倍
- `MapNavigator` 的 7.93 units/度属**另一套坐标系**（`navi_config.h`），不经过转向动作，不能互相代入
- evidence 与 reports 已 gitignore；对外交付用 `pack_report.py` 打包
- 测量脚本**不走控制器**，直连 CDP——为了排除控制器层干扰，这是刻意的

## 六、路径与命令

工作树：`D:\桌面\常用\面向MMAEND项目\MaaEnd-linux-adapt`
测试资产：`…\tools\pr6696-tests\`
结论文档：`T5-方案总览.md`（主）、`T5i`、`T5j`、`T5j-10轮统计.md`、`T1b`、`INDEX-留档.md`（速查）
控制器：`D:\桌面\常用\面向MMAEND项目\MaaEnd-src\tools\cloud-web-linux\cdp_controller.py`
harness：`D:\桌面\常用\面向MMAEND项目\cloudweb-linux\harness\test_controller.py`

```bash
cd tools/pr6696-tests

# 灵敏度验收（需要游戏在大世界）
python3 t5j_production_path.py --port 9334 --repeat 10

# 取帧延迟七条通路
python3 t1b_frame_paths.py --port 9334 --repeat 12
python3 t1b_frame_paths.py --port 9334 --repeat 12 --view 1920x1080
python3 t1b_frame_paths.py --port 9334 --repeat 30 --paths video_jpeg75,video_jpeg90

# 打包（文档+脚本+日志+证据，含 sha256 清单）
python3 pack_report.py --tag t5j --title 生产路径补测
```

**两个必测前提**（否则数据无意义）：游戏必须已进大世界（页面上要有 `<video>`）、场景尽量静止。
`t1b` 自带换帧守卫与压缩比守卫，会自己报「不在游戏内」。

## 七、环境与已知的坑

- WSL Ubuntu-24.04，软件渲染（无 GPU 直通）；Chrome `--remote-debugging-port=9334`
- 视口**固定 1280×720 / DSF 1**：与 720p 模板 1:1，且省 2.5× 延迟
- 从 Windows 调 WSL 时，`bash -c '…'` 的**单引号保护不了 `$VAR`/`$(…)`**，会被宿主先展开 →
  一律用字面量文件名
- Python 输出重定向到文件是块缓冲 → 加 `-u`，否则 `tail` 长时间看到空文件
- `pgrep -af <名字>` 会匹配到执行它的那条命令行本身
- 相机角与角色角是两件事：`rot` 只有靠「走一步」才能对齐镜头

## 八、建议的第一件事

未解决项里性价比最高的是 **#6807 评论草稿**：结论都已齐，只差成文，且能直接影响上游是否采纳。
其次是纵向标定（一轮十次即可出数）。>160° 回位那条是设计问题，值得单独一轮讨论。
