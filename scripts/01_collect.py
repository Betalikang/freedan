#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段1：多源采集 AI 羊毛资讯

源：
  AIHOT  —— 中文主线（latest + 关键词 search）
  GitHub —— 免费额度/试用类仓库
  HN     —— Show HN 类免费额度帖

输出：runs/<date>/raw.json
"""

import sys
import json
import time
import datetime
import urllib.parse
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "pipeline.json").read_text(encoding="utf-8"))

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def fetch(url, ua=None, timeout=25, retries=2):
    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": ua or BROWSER_UA,
            "Accept": "*/*",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2 * attempt)
    print(f"    ⚠ 失败 {url[:70]}: {type(last).__name__}")
    return None


def split_aihot_items(md):
    """AIHOT 返回的 Markdown 里，每条以 `N. [标题](链接)` 开头"""
    import re
    if not md:
        return []
    items = []
    for m in re.finditer(
            r"^(\d+)\.\s+\[([^\]]+)\]\(([^)]+)\)\n(.*?)(?=^\d+\.\s+\[|\Z)",
            md, re.S | re.M):
        body = m.group(4)
        meta = ""
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        if lines:
            meta = lines[0]
        items.append({
            "source": "aihot",
            "title": m.group(2).strip(),
            "url": m.group(3).strip(),
            "meta": meta,
            "body": body.strip()[:1200],
        })
    return items


def collect_aihot():
    out = []
    base = CFG["aihot"]["base"]
    ua = CFG["aihot"]["ua"]

    print("  · AIHOT latest (7d)")
    md = fetch(f"{base}/api/v1/agent/latest?window=7d&limit=30", ua)
    got = split_aihot_items(md)
    print(f"    {len(got)} 条")
    out.extend(got)

    if CFG["sources"].get("aihot_search"):
        for q in CFG["search_queries"]:
            enc = urllib.parse.quote(q)
            print(f"  · AIHOT search「{q}」")
            md = fetch(f"{base}/api/v1/agent/search?q={enc}", ua)
            got = split_aihot_items(md)
            print(f"    {len(got)} 条")
            out.extend(got)
    return out


def collect_github():
    if not CFG["sources"].get("github"):
        return []
    print("  · GitHub 免费额度仓库")
    url = ("https://api.github.com/search/repositories"
           "?q=free+ai+credits+OR+free+tier+ai&sort=updated&per_page=15")
    raw = fetch(url, "application/vnd.github+json")
    if not raw:
        return []
    try:
        d = json.loads(raw)
    except Exception:
        return []
    items = []
    for r in d.get("items", []):
        items.append({
            "source": "github",
            "title": r.get("full_name", ""),
            "url": r.get("html_url", ""),
            "meta": f"更新 {r.get('updated_at','')[:10]} · ★{r.get('stargazers_count',0)}",
            "body": (r.get("description") or "")[:600],
        })
    print(f"    {len(items)} 条")
    return items


def collect_hn():
    if not CFG["sources"].get("hackernews"):
        return []
    print("  · Hacker News 免费额度帖")
    q = urllib.parse.quote("free credits AI")
    raw = fetch(f"https://hn.algolia.com/api/v1/search?query={q}&tags=story&hitsPerPage=15")
    if not raw:
        return []
    try:
        d = json.loads(raw)
    except Exception:
        return []
    items = []
    for h in d.get("hits", []):
        items.append({
            "source": "hn",
            "title": h.get("title") or "",
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "meta": f"{h.get('created_at','')[:10]} · {h.get('points',0)} 分",
            "body": (h.get("story_text") or "")[:600],
        })
    print(f"    {len(items)} 条")
    return items


def dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = (it["title"] or "").strip().lower()[:60]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"采集 {date}")
    items = []
    items.extend(collect_aihot())
    items.extend(collect_github())
    items.extend(collect_hn())
    items = dedupe(items)

    path = run_dir / "raw.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    by_src = {}
    for it in items:
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1
    print(f"\n去重后 {len(items)} 条 → {path}")
    print("来源分布:", by_src)


if __name__ == "__main__":
    main()