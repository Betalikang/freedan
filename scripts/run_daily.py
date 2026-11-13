#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 羊毛日报 · 总控

一条命令跑完：采集 → 筛选 → 写稿 → 配音对齐 → 出片 → 封面 → 导入存量内容 → 聚合站

用法：
    python scripts/run_daily.py                # 今天
    python scripts/run_daily.py 2026-11-12     # 指定日期
    python scripts/run_daily.py --skip-render  # 只到写稿
    python scripts/run_daily.py --no-import    # 不重新抓 saibodan.com 的存量内容
"""

import sys
import json
import argparse
import datetime
import subprocess
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CFG = json.loads((ROOT / "pipeline.json").read_text(encoding="utf-8"))


def run(script, date, required=True):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), date],
                       cwd=str(ROOT))
    if r.returncode != 0:
        if required:
            print(f"\n✗ {script} 失败 (exit {r.returncode})")
        else:
            print(f"\n⚠ {script} 返回 {r.returncode}")
        return r.returncode
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=datetime.date.today().isoformat())
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--no-import", action="store_true",
                    help="不重新抓取 saibodan.com 的存量内容，只用现有 content/")
    args = ap.parse_args()
    date = args.date

    print("=" * 60)
    print(f"AI 羊毛日报 · {date}")
    print("=" * 60)

    print("\n[1/6] 采集")
    if run("01_collect.py", date) != 0:
        return 1

    print("\n[2/6] 筛选")
    code = run("02_select.py", date, required=False)
    if code == 3:
        print("\n今天合格羊毛不足，不出片。采集数据已保留：")
        print(f"  {ROOT / 'runs' / date / 'freebies.json'}")
        print("\n[7/8] 聚合站（仅刷新已有数据）")
        run("07_site.py", date, required=False)
        return 0
    if code != 0:
        return 1

    print("\n[3/6] 写稿")
    if run("03_compose.py", date) != 0:
        return 1

    if args.skip_render:
        print("\n✓ 已到写稿阶段（跳过配音与出片）")
        return 0

    print("\n[4/6] 配音对齐")
    if run("04_narrate.py", date) != 0:
        return 1

    print("\n[5/6] 出片")
    if run("05_render.py", date) != 0:
        return 1

    print("\n[6/6] 封面")
    if run("06_cover.py", date) != 0:
        return 1

    print("\n[7/8] 导入存量内容")
    # 依赖 saibodan.com 在线，所以失败只警告不阻断——content/ 里已有上次的数据，
    # 站点照样能建，只是福利库不会刷新到当天。
    if "--no-import" not in sys.argv:
        run("08_import_site.py", date, required=False)
    else:
        print("  --no-import：跳过，沿用现有 content/")

    print("\n[8/8] 聚合站")
    if run("07_site.py", date) != 0:
        return 1

    run_dir = ROOT / "runs" / date
    print("\n" + "=" * 60)
    print(f"✓ 完成 · {run_dir}")
    for f in ["video.mp4", "cover_16x9.png", "cover_4x3.png", "cover_3x4.png",
              "publish.md", "script.md"]:
        p = run_dir / f
        if p.exists():
            print(f"  {f:18} {p.stat().st_size/1024:.0f} KB")
    idx = ROOT / "site" / "index.html"
    if idx.exists():
        print(f"  {'site/index.html':18} {idx}")
    print("  站点已重建；推送到 GitHub/Cloudflare Pages 请跑 python scripts/deploy_site.py")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())