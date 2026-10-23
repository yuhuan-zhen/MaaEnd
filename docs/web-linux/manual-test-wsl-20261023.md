# 在 WSL 里手动跑一轮（2026-10-23）

给一份「一次只做一件事」的手动测试流程。全部在 WSL 里执行，产物落到 Windows 桌面。

## 0. 前置（这台机器已经具备）

| 项 | 位置 |
|---|---|
| sway | `/usr/bin/sway` |
| Chrome | `/usr/bin/google-chrome`（155.x） |
| maafw | `maa` python 包 + `/root/maaend/maafw` |
| 上游资源 | `/root/maaend/resource`（262 MB） |
| 仓库 | `/mnt/d/maaend-upstream` |
| launcher | `/mnt/d/UserDocuments/MaaEnd-review/launcher-draft/cloud-web-launch/cloud-web-launch-linux` |

> 已经在 WSL 提示符里（`root@yuhuan`）就**不要**再敲 `wsl -d ...`，那是 Windows 侧的命令。

第一步永远先确认这三件事：

```bash
cd /mnt/d/maaend-upstream
./web/linux/wsl/manual_test.sh status
```

## 1. `host` —— 不用账号，验“起得来 + 注入生效 + 视口对”

```bash
./web/linux/wsl/manual_test.sh host
```

它会：起 sway（1280×720 无头输出）→ 起 kiosk Chrome → 等 CDP → 注入输入策略与抹平脚本
→ 打开 `tests/fake_cloud_page.html` → 打印状态/检查 → 截图到 `D:\桌面\maaend-manual\host.png`。

**本次实测输出**：

```json
{"ready":true,"mode":"compositor","cdp":"http://127.0.0.1:9334",
 "control":"unix:/tmp/maaend-cloud-web-16958.sock",
 "wlr":"/run/user/0/wayland-1","pid":16958,"browser_pid":16972}

state: page=landing  account=unknown  video_ready=false
       viewport=1280x720  device_pixel_ratio=1  start_target={x:640,y:360}
checks: flattenTag=true  ball=1  latency=1  relativeMove=function
        webgl2Disabled=true  focusNoop=true
shot:   1280x720，中心像素 (239,239,239) = 「开始游戏」按钮
```

**判读**：`viewport=1280x720 / dpr=1` 说明几何已经和 PC 客户端对齐（模板不用重裁）；
`flattenTag=true` 说明悬浮球/延迟角标那套注入生效。

## 2. `wlr` —— 验“框架内置 Linux 控制器能抓这一屏”

```bash
./web/linux/wsl/manual_test.sh wlr
```

它不写任何自定义控制器，直接用 `LinuxController({screencap_method:1, input_method:1, wlr_socket_path})`
（1 = Wlr）连上去抓一帧。

**本次实测**：

```json
{"ok":true,"kind":"LinuxController","connected":true,
 "shape":[720,1280,3],"mean":[19.5,19.5,19.5]}
```

截图 `wlr.png` 与 CDP 那张**像素一致**（中心 239,239,239；左上 17,17,17）——
说明「合成器截图」和「CDP 截图」在 1280×720 下是同一个画面，只是链路上少/多一次重采样。

## 3. `login` —— 真页面，扫码登录

```bash
./web/linux/wsl/manual_test.sh login
```

它起来后先截一张图到 `D:\桌面\maaend-manual\login.png`（正常约 700 KB、1280×720；如果只有几 KB 说明页面还没渲染完）。
**打开那张图扫二维码**（云终末地支持扫码登录），之后脚本每 3 秒打印一次页面状态，最多等 300 秒，直到 `video_ready=true`。

实测（2026-10-23 23:13）：登录页 `page=landing`、`viewport=1280x720`、`dpr=1`、截图 698 KB。

> 浏览器是跑在无头 sway 里的 kiosk 窗口，你的桌面上看不到它——所以登录只能靠截图扫码。

## 4. `daily` —— 跑一轮日常（带兼容性阶梯）

```bash
# L3 = 现状（启动链 + 结构覆盖 + 数值覆盖 全加载）
./web/linux/wsl/manual_test.sh daily --only 3,4,5

# L1 = 只加载数值覆盖（验证结构覆盖能不能删）
./web/linux/wsl/manual_test.sh daily --ladder L1 --only 3,4,5

# L0 = 纯上游（验证「别人写的节点能不能直接用」）
./web/linux/wsl/manual_test.sh daily --ladder L0 --only 3,4,5
```

阶梯的定义见 `docs/web-linux/overlay-compatibility-ladder-20261023.md`。

## 5. `stop` —— 收尾（一定要跑）

```bash
./web/linux/wsl/manual_test.sh stop
```

它会 `--stop` 优雅关浏览器（先 flush 登录态）、再清 sway。

---

## 本次在 WSL 里踩到的两个坑（已修进 launcher）

| 现象 | 原因 | 修法 |
|---|---|---|
| 固定 `--remote-debugging-port=9334` 时 launcher 永远等不到 `DevToolsActivePort` | Chrome **只在 port=0 时**才写这个文件 | 固定端口时改成轮询 `http://127.0.0.1:PORT/json/version` |
| Chrome 起得来但窗口不在 sway 里、一帧全黑，日志末尾 `GPU process isn't usable. Goodbye.` | root + WSL 下 GPU 进程自己的 sandbox 起不来（`error_code=1002`） | compositor 模式加 `--use-angle=swiftshader --enable-unsafe-swiftshader --disable-gpu-sandbox --disable-dev-shm-usage` |

第二条是硬坑：**WSL/容器里没有 GPU，必须显式走 swiftshader 且关掉 GPU 沙箱**，否则 Chrome 会在 GPU 初始化阶段直接 FATAL 退出，表现是“CDP 连得上、但合成器里没有窗口”。

| 现象 | 原因 | 修法 |
|---|---|---|
| 真页面视口变成 **1248×591**（假页面却是 1280×720） | `fixViewport()` 里的 `Browser.setWindowBounds({windowState:"normal"})` **会退出 kiosk**，Chrome 带出标题栏 | compositor 模式只读视口、不写窗口尺寸；kiosk 本身就是输出尺寸 |
| 第二次 attach 时报 `TypeError: Cannot redefine property: getContext` | 策略脚本把 `getContext` / `window.focus` 定义成 `configurable: false`，重复注入必炸 | 两个脚本开头加 `if (window.__maaPolicyInstalled) return;` 守卫，注入异常也不再中断体检 |
| `./manual_test.sh: /usr/bin/env: 'bash\r': No such file or directory` | 脚本被写成 CRLF（Windows 编辑器） | `sed -i 's/\r$//' web/linux/wsl/manual_test.sh`；提交前确认 LF |
