# pr6696 验证套件

针对 **#6696**（`feat/web-linux-layer`，Linux 侧云终末地网页端参考实现）的实测脚本。
每一项都对应 PR 里的一句话断言；测出来的结果直接可以贴进 **#6807** 的讨论。

独立于 `tools/linux-adapt/`：那边是学习与工程线（C++ L0-L6），这边只做「验证 #6696 的说法是否成立」。

## 七项与 PR 断言的对应

| 脚本 | 验证 #6696 的哪句话 | 需要什么 |
| --- | --- | --- |
| `t1_frame_latency.py` | 「CDP 取帧可用」，以及 #6807 引用的「1080p JPEG ≈190 ms」口径 | Chrome、一张真实帧 |
| `t2_jpeg_recognition.py` | 有损编码是否掉识别命中 | numpy + pillow；后续 pnpm |
| `t3_two_clients.py` | 「控制器与外部探针同时连同一页面」（#6807 风险 3） | Chrome |
| `t4_resource_layer_ab.py` | 「不加载 `resource_linux`」这条结论 | maafw、sway、**游戏画面** |
| `t5_relative_move_split.py` | 127 这个上限的依据 | Chrome；game 需真实页面 |
| `t6_chrome_flags.py` | Chrome 启动参数清单（`--app`/端口/独立 profile/防节流/DSF） | Chrome |
| `t7_env_pack.py` | 「别人能不能复现」（docs/08 §T7） | 前面几项的产物 |

## 跑法

标准库里就能跑（除 t2 / t4）：

```bash
cd tools/pr6696-tests

python3 t5_relative_move_split.py --mode browser     # 最快，二值结论
python3 t1_frame_latency.py                          # 取帧延迟与编码代价
python3 t3_two_clients.py                            # 两个客户端并发
python3 t6_chrome_flags.py                           # 启动参数消融

# 需要额外依赖
uv run --with numpy --with pillow python t2_jpeg_recognition.py --images <png目录>
uv run --with maafw --with numpy python t4_resource_layer_ab.py --repo ../../MaaEnd-src

python3 t7_env_pack.py --check-frames                # 汇总成一份证据包
```

产物都在 `evidence/`（已 gitignore），每项一个带时间戳的子目录，内含
`env.txt`（六项环境）、`summary.json`（统计值）、`raw.json`（原始采样）、`command.sh`（跑的命令）。

## 设计原则

1. **先给方法，再给数字**：每个脚本的 docstring 写清「要回答什么、怎么判读」，判读标准写死在输出里
2. **统计量必须成组**：median / p95 / min / max / n 全给，只报均值会被质疑
3. **对照不可省**：t4 有「加载 / 不加载」两组，t6 每条参数都有「有 / 无」两次
4. **能二值判的优先**：t5 读页面收到的 `movementX` 数值，而不是「看画面转了多少」
5. **不确定就标出来**：docstring 里明确写「本脚本不能证明什么」

## 覆盖 / 未覆盖

### 覆盖

- CDP 四条取帧路径的耗时与每帧 base64 字节数
- 两个 WebSocket 会话同时连同一页面：共存、互相挤占、双向输入
- 页内注入的 `movementX` 是否精确等于请求值
- Chrome 五个启动参数各自去掉后的可观察症状
- `resource_linux` 覆盖层对转视角的破坏（配对 NCC）
- JPEG 重编码对识别素材的影响（素材生成 + 待跑的回归清单）

### 未覆盖（写清楚，避免被当成已验）

| 项 | 原因 |
| --- | --- |
| `--remote-debugging-pipe` 与端口客户端混合并发 | pipe 必须在拉起浏览器时占用 fd，无法给已启动的浏览器后加 |
| SDK 内部是否截断 `movementX` | 页面只能看到入参，截断在 SDK 内部，靠画面转角间接判断（t4 + t5 game） |
| 真实 DPI 125% / 150% | 本机 WSLg 固定 DSF 1，需要真机 |
| 多显示器 | 同上 |
| 长时运行（>1h）的内存与 fd 稳定性 | 需要专门的浸泡测试 |
| JPEG 对识别的最终结论 | t2 只产素材与清单，最终判定要跑 `pnpm test` 回归 |

## 结果怎么用

1. `python3 t7_env_pack.py --check-frames` → 得到 `pr6696-evidence-pack.zip`
2. 关键数字抄进 `docs/07-issue6807-评论草稿.md` 对应位置
3. 对外只贴「实测 / 换算 / 未验证」三档明确标注的内容
