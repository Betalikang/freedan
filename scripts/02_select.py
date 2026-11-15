#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段2：从原始资讯里筛选出"羊毛"条目并结构化

硬性门槛：benefit 必须含具体数字或时长，否则丢弃。
输出：runs/<date>/freebies.json
"""

import sys
import json
import re
import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "pipeline.json").read_text(encoding="utf-8"))
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


# ---------------------------------------------------------------- 历史去重
# 之前 dedupe() 只在当天这一批里去重，完全不看往期。结果是同一个促销天天复发：
# Higgsfield 的折扣连报 4 天、Voloshow 连报 4 天，观众看到的是同一批东西。
# 这里把往期 runs/<date>/freebies.json 读进来，按 URL 和归一化名称比对，
# 把报过的剔掉，只留今天第一次出现的。

_NAME_JUNK = re.compile(
    r"[\s\-_—–()（）\[\]【】{}:：·.,，。!！?？/\\|+＋&＆\"'`~￥$]+")


def norm_name(s):
    return _NAME_JUNK.sub("", (s or "").lower())


def load_history(today):
    """往期已报过的羊毛 → (URL→日期列表, 归一化名称→日期列表)"""
    seen_url, seen_name = {}, {}
    runs = ROOT / "runs"
    if not runs.is_dir():
        return seen_url, seen_name
    for d in sorted(runs.iterdir()):
        if not d.is_dir() or d.name == today:
            continue
        f = d / "freebies.json"
        if not f.exists():
            continue
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        for it in items:
            u = (it.get("source_url") or "").strip()
            if u:
                seen_url.setdefault(u, []).append(d.name)
            n = norm_name(it.get("name"))
            if n:
                seen_name.setdefault(n, []).append(d.name)
    return seen_url, seen_name


def history_hits(name, url, seen_url, seen_name):
    """这条羊毛往期报过吗？返回出现过的日期列表（空列表=全新的）"""
    hits = set(seen_url.get(url, ())) if url else set()
    n = norm_name(name)
    if n:
        if n in seen_name:
            hits |= set(seen_name[n])
        else:
            # 名称会变形："Higgsfield（Claude Fable 5.2）" vs "Higgsfield 订阅"
            # vs "Higgsfield AI年度最大折扣"。取前缀包含关系判同一个主体。
            for hn, dates in seen_name.items():
                if len(hn) < 3 or len(n) < 3:
                    continue
                short, long = (n, hn) if len(n) <= len(hn) else (hn, n)
                if long.startswith(short):
                    hits |= set(dates)
    return sorted(hits)


_DEADLINE_PATTERNS = (
    re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})"),
    re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"),
)


def parse_deadline(text):
    """『2026-12-01』『1月7日』『11月13日24点』→ date；解析不出返回 None"""
    if not text:
        return None
    t = str(text)
    for pat in _DEADLINE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        g = m.groups()
        if len(g) == 3:
            year, month, day = int(g[0]), int(g[1]), int(g[2])
        else:
            year, month, day = datetime.date.today().year, int(g[0]), int(g[1])
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None
    return None


# 只认「最近刚过期」的。像「1月7日」这种没写年份的，默认填当前年份会算成去年 1 月，
# 差三百多天——那更可能是跨年的活动（赛事周期横跨 11 月到次年 1 月），不是真过期，
# 交给人工判断，不要自动剔除。
# 下界是 1 不是 0：今天截止的促销今天仍然能领，日报就是当天发的，不能自己枪掉。
EXPIRE_WINDOW_DAYS = 90


def is_expired(dl, today):
    if not dl:
        return False
    delta = (today - dl).days
    return 1 <= delta <= EXPIRE_WINDOW_DAYS


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    raw = json.loads((run_dir / "raw.json").read_text(encoding="utf-8"))
    print(f"筛选 {len(raw)} 条原始资讯")

    # saibodan.com 带来的条目已经是结构化、已核验的，直接采用，不过 LLM
    structured = []
    loose = []
    for it in raw:
        sb = it.get("sb") if isinstance(it, dict) else None
        if it.get("source") == "saibodan" and isinstance(sb, dict) and sb.get("name"):
            structured.append(sb)
        else:
            loose.append(it)
    if structured:
        print(f"  · saibodan.com 结构化条目 {len(structured)} 条，直接采用")

    drop = CFG["thresholds"]["min_heat"]
    all_items = list(structured)
    batches = list(chunk(loose, 25))
    for i, b in enumerate(batches, 1):
        try:
            all_items.extend(extract_batch(b, i, len(batches)))
        except Exception as e:
            print(f"    ⚠ 批次 {i} 失败: {e}")

    items = dedupe(normalize(all_items))
    items = [x for x in items if x["heat"] >= drop]
    items.sort(key=lambda x: (-x["heat"], x["name"]))

    # 往期报过的、以及已经过期的，都不算"今天能领的羊毛"
    use_history = CFG["thresholds"].get("history_dedup", True)
    seen_url, seen_name = load_history(date) if use_history else ({}, {})
    today_date = datetime.date.fromisoformat(date)

    fresh, repeats, expired = [], [], []
    for it in items:
        if use_history:
            hits = history_hits(it["name"], it["source_url"], seen_url, seen_name)
            if hits:
                repeats.append((it, hits))
                continue
        dl = parse_deadline(it.get("deadline"))
        if is_expired(dl, today_date):
            expired.append((it, dl))
            continue
        fresh.append(it)

    items = fresh
    path = run_dir / "freebies.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n合格羊毛 {len(items)} 条（门槛 heat≥{drop}）")
    for it in items:
        print(f"  [{it['heat']}] {it['name']}: {it['benefit'][:44]}")
    if repeats:
        print(f"\n  ↩ {len(repeats)} 条往期已报过，已跳过：")
        for it, hits in repeats:
            print(f"    - {it['name'][:26]}（{hits[0]} 起已报 {len(hits)} 次）")
    if expired:
        print(f"\n  ⏰ {len(expired)} 条已过期，已跳过：")
        for it, dl in expired:
            print(f"    - {it['name'][:26]}（截止 {dl.isoformat()}）")
    if not items and (repeats or expired):
        print("\n今天没有新的合格羊毛——上面的都是复发或过期的。不出片。")
    return 0 if len(items) >= CFG["thresholds"]["min_items_for_video"] else 3


if __name__ == "__main__":
    sys.exit(main())