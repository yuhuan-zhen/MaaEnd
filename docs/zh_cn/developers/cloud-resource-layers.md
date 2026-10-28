# 开发手册 - 云终末地资源层分工

云终末地（CloudADB）在 `resource_adb` 之上叠了两层资源：`resource_cloud_common` 与 `resource_cloud`。
把「与平台无关的识别差异」和「某个客户端独有的差异」分开，避免后续接入 Windows 云客户端时整套复制。

## 三层职责

| 层 | 放什么 | 例子 |
| -------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------- |
| `resource_adb` | 所有 adb-like 客户端共用的触摸 / 输入 / 退出实现 | `__ScenePrivateAnyExit`、`__ScenePrivateExitPhoto`、`__ScenePrivateBackPill` |
| `resource_cloud_common` | 进入游戏后、只涉及颜色 / 模板 / ROI 的识别差异（与客户端无关） | 按钮底色、活动红点、物品颜色、终端选中色 |
| `resource_cloud` | 云终末地 adb 客户端独有、且与登录界面 / 触摸布局相关的覆盖 | `__ScenePrivateLogin`（News 模板 + adb 专属 ROI） |

加载顺序（`assets/interface.json` 的 `attach_resource_path`）：

```text
resource_adb → resource_cloud_common → resource_cloud
```

跨目录是字段级深合并：后加载的层只覆盖它写出的字段，数组（`next` / `template` / `lower` / `upper`）整段替换。

## 新客户端（如 Windows 云客户端）怎么接

1. 新建 `resource_cloud_<平台>`（例如 `resource_cloud_web`），只放**该平台独有**的差异：模板重新抠图、ROI 随窗口几何调整、平台 UI（窗口边框、退出按钮）。
2. 在 `assets/interface.json` 里给该控制器写 `attach_resource_path`：`./resource_adb` → `./resource_cloud_common` → `./resource_cloud_<平台>`。
3. 不要把 `resource_cloud`（adb 专属）挂给别的客户端。

判据：**同一段识别逻辑如果在两个客户端上都能用，就属于 common；只要有一处要改图或改 ROI，就属于平台层。**

## 维护规则

- 新增颜色 / 阈值 / 模板覆盖前先确认它是不是「进入游戏后」的识别参数：是 → `resource_cloud_common`；涉及登录界面、触摸退出、时序 → 留在平台层。
- 改完 `resource_cloud_common` 后跑 `pnpm check`；拆层属于纯结构改动，合并结果必须逐节点等价（可用 `res.get_node_data()` 对比拆分前后）。
- `tools/i18n/sync_ocr_expected.py` 会扫描这三层的 `pipeline/`，新增资源包目录时同步加进去。
