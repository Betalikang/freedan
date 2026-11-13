#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段2：从原始资讯里筛选出"羊毛"条目并结构化

硬性门槛：benefit 必须含具体数字或时长，否则丢弃。
输出：runs/<date>/freebies.json
"""

import sys
import json
import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
sys.path.insert(0, CFG["paths"]["skill_scripts"].replace("/", "\\"))

import llm_analyzer as L   # noqa: E402


def chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


PROMPT = """你是 AI 领域的福利信息编辑。从下面的资讯里挑出**真正的羊毛**：
免费额度、限时免费、赠送、限时折扣、免费试用、无门槛送额度。

## 判定标准（严格执行）
- ✅ 要：有具体数字或时长，例如"3 天免费不限量"、"每月 35 个赠金"、"送 100 万 tokens"、"5 折"
- ❌ 不要：只有"免费账户可用"这类没有具体额度的描述
- ❌ 不要：纯产品发布、融资、诉讼、观点文章
- ❌ 不要：需要付费订阅才能参与的（除非本身就是折扣）
- ❌ 不要：网站首页、通用"免费清单"、聚合目录页 —— 这些不是可核验的当日活动
  判断依据：链接指向首页（如 example.com、example.com/home）或描述里没有明确的活动主体

## 输出
只输出 JSON：{{"items": [
  {{
    "name": "产品/公司名，简短",
    "benefit": "能拿到什么，必须含具体数字或时长",
    "condition": "领取条件，简短；未说明写'未说明'",
    "deadline": "截止时间；长期有效写'长期'；没有写 null",
    "heat": 1到5的整数（免费+无门槛+额度大=5）,
    "confidence": "high/medium/low",
    "source_url": "对应条目的 AIHOT 链接或原文链接"
  }}
]}}
没有符合条件的返回 {{"items":[]}}。不要解释。

## 资讯（JSON）
{payload}"""


def extract_batch(batch, idx, total):
    payload = json.dumps(
        [{"i": it.get("title"), "u": it.get("url"), "m": it.get("meta"),
          "b": (it.get("body") or "")[:500], "s": it.get("source")} for it in batch],
        ensure_ascii=False, indent=1)
    print(f"  批次 {idx}/{total}（{len(batch)} 条）...")
    out = L.call_llm(
        [{"role": "user", "content": [{"type": "text", "text": PROMPT.format(payload=payload)}]}],
        max_tokens=20000)
    data = L.extract_json(out) or {}
    items = data.get("items") or []
    print(f"    → {len(items)} 条候选")
    return items


HOMEPAGE_HINTS = ("/home", "/index", "/", "/pricing", "/features")


def is_homepage_or_listing(url, name, benefit):
    """首页/通用清单不可核验，剔除"""
    if not url:
        return True
    low = url.lower().split("?")[0].rstrip("/")
    # 只剩域名 = 首页
    parts = low.split("/")
    if len(parts) <= 3:
        return True
    # 描述里出现"清单/列表/合集/directory/list"且没有具体活动主体
    for w in ("清单", "列表", "合集", "directory", "list of", "curated"):
        if w in (name + benefit).lower():
            return True
    return False


def has_concrete(benefit):
    """benefit 必须含数字或时长，否则视为不合格"""
    import re
    if not benefit or not isinstance(benefit, str):
        return False
    return bool(re.search(r"\d", benefit)) or any(
        w in benefit for w in ("长期", "永久", "不限量", "无限"))


def normalize(items):
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        benefit = (it.get("benefit") or "").strip()
        if not name or not has_concrete(benefit):
            continue
        if is_homepage_or_listing(it.get("source_url") or "", name, benefit):
            print(f"    ✗ 剔除（首页/清单）: {name[:24]}")
            continue
        try:
            heat = int(it.get("heat") or 3)
        except (TypeError, ValueError):
            heat = 3
        out.append({
            "name": name,
            "benefit": benefit,
            "condition": (it.get("condition") or "未说明").strip(),
            "deadline": it.get("deadline"),
            "heat": max(1, min(5, heat)),
            "confidence": (it.get("confidence") or "medium").strip(),
            "source_url": (it.get("source_url") or "").strip(),
        })
    return out


def dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = it["name"].lower().replace(" ", "")[:20]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    raw = json.loads((run_dir / "raw.json").read_text(encoding="utf-8"))
    print(f"筛选 {len(raw)} 条原始资讯")

    drop = CFG["thresholds"]["min_heat"]
    all_items = []
    batches = list(chunk(raw, 25))
    for i, b in enumerate(batches, 1):
        try:
            all_items.extend(extract_batch(b, i, len(batches)))
        except Exception as e:
            print(f"    ⚠ 批次 {i} 失败: {e}")

    items = dedupe(normalize(all_items))
    items = [x for x in items if x["heat"] >= drop]
    items.sort(key=lambda x: (-x["heat"], x["name"]))

    path = run_dir / "freebies.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n合格羊毛 {len(items)} 条（门槛 heat≥{drop}）")
    for it in items:
        print(f"  [{it['heat']}] {it['name']}: {it['benefit'][:44]}")
    return 0 if len(items) >= CFG["thresholds"]["min_items_for_video"] else 3


if __name__ == "__main__":
    sys.exit(main())