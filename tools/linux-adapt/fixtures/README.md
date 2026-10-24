# fixtures

测试与解析用的固定输入。**只放自己的东西，不放上游源码副本。**

## 这里的文件

| 文件 | 用途 |
| --- | --- |
| `expected_keys.json` | 24 个键值的期望表（VK → evdev → keysym），`PLAN-键码验证.md` 的 B 层测试依据 |

## 为什么不放 `/tmp`

WSL 实例重启会把 `/tmp` 清空（2026-10-25 已踩到一次，`VkToEvdev.h` 副本丢失导致脚本报 `FileNotFoundError`）。所有需要跨调用保留的 fixture 一律放这里。

## 上游头文件不要提交

`VkToEvdev.h` 之类是 MaaFramework 的源码，按第 06 篇的 permalink 现取现用：

```bash
curl -s "https://raw.githubusercontent.com/MaaXYZ/MaaFramework/0fc6025c2fc224a171b57d89505e8d47acd2a8b1/source/MaaLinuxControlUnit/Input/VkToEvdev.h" \
  -o fixtures/VkToEvdev.h     # 已被 .gitignore 忽略
```
