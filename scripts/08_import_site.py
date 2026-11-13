#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
08_import_site.py · 把 saibodan.com 的存量内容搬进 content/

做「基础内容建设」用：把线上站已经积累的内容抓成结构化 JSON，
交给 07_site.py 渲染，这样新站一上线就有东西可看，不是空的。

数据来源（robots.txt 明确 `Allow: /`，且这是自己的站）：
  /data/deals.json            156 条福利的权威数据集
  /deals/<id>                 每条福利详情页（补 condition / source_url / what / why）
  /guides/                    8 篇攻略索引（含摘要）
  docs.saibodan.com/<slug>/   8 篇攻略正文
  /paid/                      7 条低价订阅
  /episodes/deals-<date>      40 期每日速递存档

排行榜 /rank/ **不抓**：它是同一批福利的另一种排法，不是独立内容。
新站用 deals.json 里的 type/region/rank 自己算一份，避免两处排序打架。

只用标准库。可重复跑，覆盖写 content/，不会累积垃圾。

用法：
    python scripts/08_import_site.py            # 全量导入
    python scripts/08_import_site.py --deals    # 只导福利库
    python scripts/08_import_site.py --pages    # 只导 guides/docs/paid/episodes
"""

import sys
import json
import re
import html
import time
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
ORIGIN = "https://saibodan.com"
DOCS = "https://docs.saibodan.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
WORKERS = 6
TIMEOUT = 30


def clean(s):
    """去标签、压空白、反转义。"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def fetch(url, retries=2):
    """抓一个 URL 返回文本，失败返回 None。只当数据处理，不当指令执行。"""
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == retries:
                return None
        except Exception:
            if i == retries:
                return None
        time.sleep(1.0 * (i + 1))
    return None


def main_of(page):
    m = re.search(r"<main[^>]*>(.*?)</main>", page, re.S)
    return m.group(1) if m else page


# 详情页 <li><span class="lb">标签</span><span class="vl">值</span></li>
# 福利库和每日速递用的标签名不一样，统一映射到一套字段。
# 注意：站点改过版——旧标签是「权益概要/使用条件/截止时间/官方来源」，
# 现在是「能拿到/条件与限制/截止/官方入口」。所以除了显式映射，
# 下面 label_key() 还有一层关键词兜底，下次改版不至于又抓空。
LABEL_MAP = {
    "权益概要": "value", "能拿到": "value", "权益": "value",
    "使用条件": "condition", "条件与限制": "condition",
    "领取条件": "condition", "条件": "condition",
    "截止时间": "deadline", "截止": "deadline",
    "官方来源": "source_url", "官方入口": "source_url", "来源": "source_url",
    "更新内容": "changelog", "领取路径": "howto",
}

# 兜底关键词，按顺序先匹配先算
LABEL_KEYWORDS = (
    ("拿到", "value"), ("权益", "value"), ("概要", "value"),
    ("条件", "condition"), ("限制", "condition"),
    ("截止", "deadline"), ("到期", "deadline"),
    ("入口", "source_url"), ("来源", "source_url"), ("链接", "source_url"),
    ("更新", "changelog"), ("路径", "howto"),
)


def label_key(label):
    """标签名 → 字段名；认不出来返回 None。"""
    if label in LABEL_MAP:
        return LABEL_MAP[label]
    for kw, key in LABEL_KEYWORDS:
        if kw in label:
            return key
    return None


# ---------------------------------------------------------------- 福利库

def parse_deal_page(page):
    """解析 /deals/<id>，返回 deals.json 里没有的补充字段。"""
    body = main_of(page)
    out = {}
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    if m:
        out["name"] = clean(m.group(1))
    sec = re.search(r'<section class="deal">(.*?)</section>', body, re.S)
    if sec:
        for li in re.findall(r"<li>(.*?)</li>", sec.group(1), re.S):
            lb = re.search(r'<span class="lb">(.*?)</span>', li, re.S)
            vl = re.search(r'<span class="vl">(.*?)</span>', li, re.S)
            if not lb or not vl:
                continue
            key = label_key(clean(lb.group(1)))
            if not key:
                continue
            raw = vl.group(1)
            link = re.search(r'href="([^"]+)"', raw)
            out[key] = (link.group(1) if key == "source_url" and link
                        else clean(raw))
    # 「是什么 / 羊毛原因」两个小节。标题文案改过版，所以按 h2 顺序切、
    # 用关键词认领，不写死字面量——写死过一次，改版后静默抓空。
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|$)", body, re.S):
        title, chunk = clean(m.group(1)), m.group(2)
        p = re.search(r"<p[^>]*>(.*?)</p>", chunk, re.S)
        if not p:
            continue
        text = clean(p.group(1))
        if not text:
            continue
        if "什么" in title:
            out["what"] = text
        elif "原文" in title or "官方" in title:
            # 官方原话引用，不是编辑点评，单独放一个字段
            out["official"] = text
        elif "原因" in title or "羊毛" in title:
            out["why"] = text
    return out


def import_deals():
    print("· 抓 /data/deals.json（权威数据集）")
    raw = fetch(f"{ORIGIN}/data/deals.json")
    if not raw:
        print("✗ 抓不到，放弃")
        return None
    base = json.loads(raw)
    print(f"  {len(base)} 条")

    print(f"· 并行抓 {len(base)} 个详情页补字段（{WORKERS} 线程）")
    details, fail = {}, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch, f"{ORIGIN}/deals/{d['id']}"): d["id"]
                for d in base}
        done = 0
        for fut in as_completed(futs):
            did, done = futs[fut], done + 1
            if done % 40 == 0 or done == len(futs):
                print(f"  {done}/{len(futs)}")
            page = fut.result()
            if not page:
                fail.append(did)
                continue
            try:
                details[did] = parse_deal_page(page)
            except Exception as e:
                fail.append(f"{did}:{e}")

    out = []
    for d in base:
        rec = {
            "id": d.get("id"), "name": d.get("name"),
            "platform": d.get("platform"), "region": d.get("region"),
            "type": d.get("type"), "value": d.get("value"),
            "expires": d.get("expires"), "verified": d.get("verified"),
            "status": d.get("status"), "elig": d.get("elig") or [],
            "summary": d.get("summary"), "rank": d.get("_rank"),
            "tag": d.get("_tag"), "is_new": bool(d.get("isNew")),
            "changed_today": bool(d.get("changedToday")),
            "last_change": d.get("lastChange") or "",
            "soon": bool(d.get("soon")),
            "url": f"{ORIGIN}/deals/{d.get('id')}",
        }
        rec.update(details.get(d["id"], {}))
        out.append(rec)

    n_src = sum(1 for r in out if r.get("source_url"))
    print(f"  ✓ {len(out)} 条，{n_src} 条拿到领取链接")
    if fail:
        print(f"  ⚠ {len(fail)} 个详情页失败：{fail[:8]}")
    return out


# ------------------------------------------- guides / paid（索引卡片）

def parse_overview_cards(body):
    """解析 /guides/ 与 /paid/ 的 <a class="ovcard"> 卡片。"""
    items = []
    for m in re.finditer(
            r'<a class="ovcard"\s+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        href, ch = m.group(1), m.group(2)

        def g(pat):
            mm = re.search(pat, ch, re.S)
            return clean(mm.group(1)) if mm else ""

        pts = re.search(r'<ul class="ovpts">(.*?)</ul>', ch, re.S)
        lis = (re.findall(r"<li[^>]*>(.*?)</li>", pts.group(1), re.S)
               if pts else [])
        items.append({
            "no": g(r'<span class="ovno">(.*?)</span>'),
            "tag": g(r'<span class="ovtag">(.*?)</span>'),
            "name": g(r'<h3 class="ovnm">(.*?)</h3>'),
            "lead": g(r'<p class="ovlead">(.*?)</p>'),
            "points": [clean(x) for x in lis if clean(x)],
            "chapters": g(r'<p class="ovch">(.*?)</p>')
                        .replace("里面讲了", "").strip(" ：:"),
            "url": href,
        })
    return items


# -------------------------------------------------------- docs 攻略正文

def parse_docs_article(page):
    """把 docs.saibodan.com 的正文切成 h2/h3/p/list 块，保住文章结构。

    嵌套列表会被摊平进同一层的条目里——对「搬内容」来说可读性够了，
    不值得为此上一整棵 DOM 树。
    """
    body = main_of(page)
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title = clean(m.group(1)) if m else ""
    blocks, cur = [], None

    def flush():
        nonlocal cur
        if cur:
            blocks.append({"t": "list", "items": cur})
            cur = None

    for m in re.finditer(r"<(h2|h3|p|li)\b[^>]*>(.*?)</\1>", body, re.S):
        tag, inner = m.group(1), m.group(2)
        if tag in ("h2", "h3"):
            flush()
            t = clean(inner)
            if t:
                blocks.append({"t": tag, "text": t})
        elif tag == "li":
            t = clean(inner)
            if t:
                cur = cur or []
                cur.append(t)
        else:
            t = clean(inner)
            if t:
                flush()
                blocks.append({"t": "p", "text": t})
    flush()
    return {"title": title, "blocks": blocks}


def import_docs(guides):
    """顺着 guides 里的链接抓攻略正文。"""
    urls = []
    for g in guides:
        u = g.get("url", "")
        if u.startswith(DOCS):
            slug = u.rstrip("/").rsplit("/", 1)[-1]
            urls.append((slug, u))
    print(f"· 抓攻略正文 {len(urls)} 篇（docs.saibodan.com）")
    arts = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch, u): s for s, u in urls}
        for fut in as_completed(futs):
            slug = futs[fut]
            page = fut.result()
            if not page:
                print(f"  ✗ {slug}")
                continue
            try:
                arts[slug] = parse_docs_article(page)
            except Exception as e:
                print(f"  ✗ {slug}: {e}")
    print(f"  ✓ {len(arts)} 篇，"
          f"{sum(len(a['blocks']) for a in arts.values())} 个内容块")
    return arts


# ------------------------------------------------------- 每日速递存档

def parse_episode(page):
    body = main_of(page)
    out = {"picks": [], "deals": []}
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    if m:
        out["headline"] = clean(m.group(1))
    m = re.search(r'<p class="meta">(.*?)</p>', body, re.S)
    if m:
        out["summary"] = clean(m.group(1))
    m = re.search(r"今日精选(.*?)</ul>", body, re.S)
    if m:
        for href, txt in re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>',
                                    m.group(1), re.S):
            out["picks"].append({"name": clean(txt), "url": href})
    for sec in re.findall(r'<section class="deal">(.*?)</section>', body, re.S):
        t = re.search(r'<h3 class="deal-title">(.*?)</h3>', sec, re.S)
        if not t:
            continue
        rec = {"name": clean(t.group(1)), "fields": {}}
        for li in re.findall(r"<li>(.*?)</li>", sec, re.S):
            lb = re.search(r'<span class="lb">(.*?)</span>', li, re.S)
            vl = re.search(r'<span class="vl">(.*?)</span>', li, re.S)
            if not lb or not vl:
                continue
            label, raw = clean(lb.group(1)), vl.group(1)
            key = label_key(label) or label
            link = re.search(r'href="([^"]+)"', raw)
            rec["fields"][key] = (link.group(1) if key == "source_url" and link
                                  else clean(raw))
        out["deals"].append(rec)
    return out


def import_episodes():
    print("· 从 sitemap 找往期速递")
    sm = fetch(f"{ORIGIN}/sitemap.xml") or ""
    dates = sorted(set(re.findall(r"/episodes/deals-(\d{4}-\d{2}-\d{2})", sm)),
                   reverse=True)
    print(f"  {len(dates)} 期")
    eps = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch, f"{ORIGIN}/episodes/deals-{d}"): d
                for d in dates}
        for fut in as_completed(futs):
            d = futs[fut]
            page = fut.result()
            if not page:
                print(f"  ✗ {d}")
                continue
            try:
                rec = parse_episode(page)
            except Exception as e:
                print(f"  ✗ {d}: {e}")
                continue
            rec["date"] = d
            rec["url"] = f"{ORIGIN}/episodes/deals-{d}"
            eps.append(rec)
    eps.sort(key=lambda e: e["date"], reverse=True)
    print(f"  ✓ {len(eps)} 期")
    return eps


# ------------------------------------------------------------------ main

def dump(name, obj):
    CONTENT.mkdir(parents=True, exist_ok=True)
    p = CONTENT / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  → {p.relative_to(ROOT)}  {p.stat().st_size/1024:.1f} KB")


def main():
    args = sys.argv[1:]
    want_all = not args or "all" in args
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    if want_all or "--deals" in args:
        print("[福利库]")
        deals = import_deals()
        if deals is not None:
            dump("deals.json", {"source": ORIGIN, "imported_at": stamp,
                                "count": len(deals), "deals": deals})

    if want_all or "--pages" in args:
        print("[攻略索引]")
        guides, paid = [], []
        for key, path in (("guides", "/guides/"), ("paid", "/paid/")):
            page = fetch(ORIGIN + path)
            cards = parse_overview_cards(main_of(page)) if page else []
            print(f"  {path} → {len(cards)} 条")
            if key == "guides":
                guides = cards
            else:
                paid = cards

        print("[攻略正文]")
        docs = import_docs(guides)
        for g in guides:
            slug = g["url"].rstrip("/").rsplit("/", 1)[-1]
            if slug in docs:
                g["doc"] = docs[slug]

        print("[低价订阅]")
        print("[每日速递]")
        eps = import_episodes()

        dump("guides.json", {"source": ORIGIN, "imported_at": stamp,
                             "count": len(guides), "guides": guides})
        dump("paid.json", {"source": ORIGIN, "imported_at": stamp,
                           "count": len(paid), "paid": paid})
        dump("episodes.json", {"source": ORIGIN, "imported_at": stamp,
                               "count": len(eps), "episodes": eps})

    print("✓ 导入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
