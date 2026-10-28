# Development Guide - Cloud Endfield Resource Layers

Cloud Endfield (CloudADB) stacks two resource layers on top of `resource_adb`: `resource_cloud_common` and `resource_cloud`.
The split keeps "recognition differences that are platform-independent" apart from "differences only one client has",
so adding a Windows cloud client later does not require copying the whole set.

## Responsibilities

| Layer | Contents | Examples |
| ----------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| `resource_adb` | Touch / input / exit behaviour shared by every adb-like client | `__ScenePrivateAnyExit`, `__ScenePrivateExitPhoto`, `__ScenePrivateBackPill` |
| `resource_cloud_common` | In-game recognition differences that only touch colour / template / ROI | button background colours, event red dots, item colours, terminal highlight |
| `resource_cloud` | Overrides unique to the adb Cloud Endfield client (login screen, touch layout) | `__ScenePrivateLogin` (News templates + adb-specific ROI) |

Load order (`attach_resource_path` in `assets/interface.json`):

```text
resource_adb → resource_cloud_common → resource_cloud
```

Merging is a field-level deep merge across directories: a later layer only overrides the fields it writes,
while arrays (`next` / `template` / `lower` / `upper`) are replaced as a whole.

## Wiring a new client (e.g. the Windows cloud client)

1. Create `resource_cloud_<platform>` (for example `resource_cloud_web`) holding only that platform's differences:
   re-cropped templates, ROIs adjusted to the window geometry, platform UI (window chrome, exit button).
2. Point the controller's `attach_resource_path` at `./resource_adb` → `./resource_cloud_common` → `./resource_cloud_<platform>`.
3. Do not attach `resource_cloud` (adb-only) to other clients.

Rule of thumb: **if the same recognition works on two clients, it belongs in common; as soon as a template or ROI must
differ, it belongs in the platform layer.**

## Maintenance rules

- Before adding a colour / threshold / template override, decide whether it is an in-game recognition parameter:
  yes → `resource_cloud_common`; login screen, touch exit or timing → keep it in the platform layer.
- Run `pnpm check` after changing `resource_cloud_common`. Splitting layers is a structural change: the merged result
  must be node-for-node equivalent (compare with `res.get_node_data()` before and after).
- `tools/i18n/sync_ocr_expected.py` scans the `pipeline/` of all three layers; add any new resource directory there too.
