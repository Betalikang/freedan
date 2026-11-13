#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段5：生成每日封面（16:9 / 4:3 / 3:4），复用 redesign 的封面模板但换数据"""

import sys
import re
import json
import html as H
import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
REDESIGN = Path(CFG["paths"]["redesign"])
sys.path.insert(0, str(REDESIGN / "scripts"))

from playwright.sync_api import sync_playwright  # noqa: E402

TEMPLATES = [
    ("cover_16x9.html", "cover_16x9.png", 1920, 1080),
    ("cover_4x3.html", "cover_4x3.png", 1600, 1200),
    ("cover_3x4.html", "cover_3x4.png", 1080, 1440),
]


def _short(t, n=16):
    """截断到 n 字；若开括号没闭合则从开括号前断开，避免留下半个括号"""
    t = str(t).strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    for o, c in (("（", "）"), ("(", ")")):
        if cut.count(o) > cut.count(c):
            i = cut.rfind(o)
            if i >= 4:
                cut = cut[:i]
                break
    return cut.rstrip(" ·、,，")


def _card(cards, i):
    if i < len(cards):
        c = cards[i]
        return {
            "NUM": c["side"]["num"],
            "LABEL": c["side"]["label"],
            "TITLE": _short(c["title"], 16),
            "NOTE": c["side"]["note"][:30],
        }
    return {"NUM": "—", "LABEL": "", "TITLE": "", "NOTE": ""}


def token_map(data):
    m = data["meta"]
    cards = data["detail"]["cards"]
    picks = data["cover"]["picks"]
    s1, s2 = _card(cards, 0), _card(cards, 1)
    p1 = picks[0] if len(picks) > 0 else {"name": "", "note": ""}
    p2 = picks[1] if len(picks) > 1 else {"name": "", "note": ""}
    return {
        "BRAND_NAME": m["brand"],
        "BRAND_SUB": m["brand_en"],
        "VOLUME": m["volume"],
        "BADGE": m["badge"],
        "EYEBROW": "今日推荐",
        "TITLE": m["title"],
        "TITLE_EN": m["title_en"],
        # 含 <em> 标签，不转义
        "SUBLINE": f'今天值得拿的 <em>{len(cards)}</em> 条',
        "SUBLINE2": data["overview"]["big_stat"]["label"],
        "S1_NUM": s1["NUM"], "S1_LABEL": s1["LABEL"],
        "S1_TITLE": s1["TITLE"], "S1_NOTE": s1["NOTE"],
        "S2_NUM": s2["NUM"], "S2_LABEL": s2["LABEL"],
        "S2_TITLE": s2["TITLE"], "S2_NOTE": s2["NOTE"],
        "P1_NAME": _short(p1["name"], 16), "P1_NOTE": p1["note"],
        "P2_NAME": _short(p2["name"], 16), "P2_NOTE": p2["note"],
        "TOTAL": m["total"],
        "TOTAL_NOTE": "条",
        "TOTAL_RIGHT": m["date"],
        "TOTAL_RIGHT_K": "更新日期",
        "FOOT_R": f"每天更新 · {m['date']}",
    }


def apply_data(html, data):
    toks = token_map(data)
    for k, v in toks.items():
        if k == "SUBLINE":
            continue
        html = html.replace("{{" + k + "}}", H.escape(str(v)))
    html = html.replace("{{SUBLINE}}", toks["SUBLINE"])

    left = sorted(set(re.findall(r"\{\{\w+\}\}", html)))
    if left:
        raise RuntimeError(f"封面模板有未替换占位符: {left}")
    return html


def render(html_path, png_path, w, h):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        pg.goto(Path(html_path).resolve().as_uri())
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": w, "height": h})
        b.close()


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    data = json.loads((run_dir / "content.json").read_text(encoding="utf-8"))

    print("生成封面...")
    css_abs = (REDESIGN / "html" / "base.css").resolve().as_uri()
    for tpl_name, out_name, w, h in TEMPLATES:
        tpl = REDESIGN / "html" / tpl_name
        if not tpl.exists():
            print(f"  ⚠ 模板缺失 {tpl_name}")
            continue
        html = apply_data(tpl.read_text(encoding="utf-8"), data)
        # 样式表用绝对路径，避免写到 runs 目录后相对路径失效
        html = html.replace('href="base.css"', f'href="{css_abs}"')
        tmp = run_dir / f"_{out_name}.html"
        tmp.write_text(html, encoding="utf-8")
        render(tmp, run_dir / out_name, w, h)
        print(f"  ✓ {out_name}  {w}x{h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
