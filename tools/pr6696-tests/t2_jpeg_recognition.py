#!/usr/bin/env python3
"""T2 · JPEG 有损对识别的影响（验证 #6696 的「有损会掉命中」风险）

这一个是「必验项」：JPEG 能显著降低取帧延迟，但模板匹配是逐像素比对的，
有损压缩会改变高频细节。到底会不会掉命中，只能拿仓库自己的测试用例来量。

做法（不另造标准）：
  1. 从测试集目录取 PNG（默认 tests/MaaEndTestset 下的识别图）
  2. 按给定质量重编码成 JPEG，再解回 PNG（模拟串流编码损失，格式回到 PNG 以便喂给框架）
  3. 计算 PSNR 与体积比，产出一张对照表
  4. 生成「替换清单」，你把图换进 tests 的副本后跑 pnpm test，逐用例比对 hits

为什么不在脚本里直接跑 pnpm test：那需要在仓库副本里替换图片并触发一整套识别回归，
属于会改动工作区的操作。脚本只做「可复现的素材生成 + 清单」，跑测试由你在副本里执行，
这样每一步都能对照、可回滚。

用法：
  python3 t2_jpeg_recognition.py --images ../MaaEnd-src/tests/MaaEndTestset --limit 30
  python3 t2_jpeg_recognition.py --images ./some-images --qualities 95,90,80
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

try:
    import numpy as np
    from PIL import Image
except ImportError:  # pragma: no cover - 环境提示
    raise SystemExit("需要 numpy 与 pillow：uv run --with numpy --with pillow python t2_jpeg_recognition.py") from None

import _common as c


def psnr(original: np.ndarray, restored: np.ndarray) -> float:
    """峰值信噪比。相同图像返回 inf。"""
    original_f = original.astype(np.float64)
    restored_f = restored.astype(np.float64)
    mse = float(np.mean((original_f - restored_f) ** 2))
    if mse == 0.0:
        return float("inf")
    return 10.0 * np.log10((255.0 ** 2) / mse)


def main() -> int:
    parser = argparse.ArgumentParser(description="T2 JPEG 对识别的影响（素材生成）")
    parser.add_argument("--images", required=True, help="PNG 目录（递归）")
    parser.add_argument("--limit", type=int, default=30, help="最多取多少张（默认 30）")
    parser.add_argument("--qualities", default="95,90,80", help="JPEG 质量列表")
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    source = pathlib.Path(args.images)
    if not source.exists():
        raise SystemExit(f"目录不存在：{source}")
    pngs = sorted(source.rglob("*.png"))[: args.limit]
    if not pngs:
        raise SystemExit(f"{source} 下没有 PNG")

    qualities = [int(q) for q in args.qualities.split(",")]
    evidence = c.Evidence("t2", pathlib.Path(args.out))
    out_root = pathlib.Path(evidence.path()) / "reencoded"
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    print(f"样本：{len(pngs)} 张，质量：{qualities}")

    rows = []
    manifest: dict[str, dict] = {}
    for quality in qualities:
        target_dir = out_root / f"q{quality}"
        target_dir.mkdir(parents=True, exist_ok=True)
        for src in pngs:
            with Image.open(src) as image:
                rgb = image.convert("RGB")
                buffer = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                buffer.close()
                rgb.save(buffer.name, format="JPEG", quality=quality, subsampling=2)
                with Image.open(buffer.name) as reloaded:
                    restored_img = reloaded.convert("RGB")
                original_np = np.asarray(rgb)
                restored_np = np.asarray(restored_img)
                digest_name = f"{src.stem}__q{quality}.png"
                restored_img.save(target_dir / digest_name, format="PNG")
                rows.append([
                    src.name, f"q{quality}",
                    f"{src.stat().st_size / 1024:.0f} KB",
                    f"{pathlib.Path(buffer.name).stat().st_size / 1024:.0f} KB",
                    f"{psnr(original_np, restored_np):.1f} dB",
                ])
                manifest.setdefault(str(src), {})[f"q{quality}"] = str(target_dir / digest_name)
                pathlib.Path(buffer.name).unlink(missing_ok=True)

    print("\n重编码结果（前 12 行）")
    c.print_table(rows[:12], ["原图", "质量", "原体积", "JPEG 体积", "PSNR"])

    if rows:
        psnrs = [float(row[4].split()[0]) for row in rows if not row[4].startswith("inf")]
        if psnrs:
            print(f"\nPSNR：median={sorted(psnrs)[len(psnrs) // 2]:.1f} dB，"
                  f"min={min(psnrs):.1f} dB")

    evidence.write_json("manifest.json", manifest)
    instructions = """# 下一步（人工执行）

1. 复制一份仓库副本（不要在原工作区改）：
   cp -a <repo> /tmp/pr6696-t2 && cd /tmp/pr6696-t2

2. 按 manifest.json 把图片替换成同名重编码版本（保持文件名与目录结构）

3. 跑识别回归：
   pnpm test

4. 比对同一批用例的 hits 与 score：
   - 全部仍命中 → JPEG 对这类识别无影响
   - 有命中变未命中 → 记下用例名，这就是「JPEG 会破坏 X 类识别」的证据
   - score 下降但未掉出阈值 → 记下分布，说明余量变小

5. 把结果贴回 evidence 目录，并在回复里按「命中 / 未命中 / score 变化」三项分别报
"""
    evidence.write_text("NEXT-STEPS.md", instructions)
    print(f"\n素材与清单已写入：{out_root}")
    print("后续步骤见 NEXT-STEPS.md（需要你在仓库副本里跑 pnpm test）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
