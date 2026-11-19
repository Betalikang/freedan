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
import re
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


def fetch(url, ua=None, timeout=25, retries=2, proxy=None):
    """proxy: 给被墙的源用，如 http://127.0.0.1:7897"""
    last = None
    opener = None
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": ua or BROWSER_UA,
            "Accept": "*/*",
        })
        try:
            if opener:
                with opener.open(req, timeout=timeout) as r:
                    return r.read().decode("utf-8", errors="replace")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2 * attempt)
    print(f"    ⚠ 失败 {url[:70]}: {type(last).__name__}")
    return None


def proxy_url():
    return (CFG.get("network") or {}).get("proxy") or None


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
    # 必须卡 stars：不卡的话这个查询会被 make.fun 的 bounty 农场占满——
    # 十几个不同账号提交一模一样的 free-model-aggregator，★0，把真实仓库全挤出去。
    min_stars = int(CFG.get("github_min_stars", 50))
    q = f"free ai credits OR free tier ai stars:>{min_stars}"
    url = ("https://api.github.com/search/repositories"
           "?q=" + urllib.parse.quote(q) + "&sort=updated&per_page=15")
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
    # 必须按时间取 + 卡时间窗。原来用 Algolia 默认的相关度排序，返回的是一两年前的
    # 老帖（Reuters 2024 的 Amazon credits、几年前的老 Show HN），日报天天搬旧闻。
    days = int(CFG.get("hn_days", 30))
    cutoff = int((datetime.datetime.now()
                  - datetime.timedelta(days=days)).timestamp())
    url = (f"https://hn.algolia.com/api/v1/search_by_date?query={q}"
           f"&tags=story&hitsPerPage=15&numericFilters=created_at_i>{cutoff}")
    raw = fetch(url)
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


def collect_rss():
    """通用 RSS/Atom 信源。只留「AI 相关」且「带免费/额度/折扣字眼」的条目——
    综合科技媒体的 RSS 每天几十条，不过滤的话 LLM 批次全被无关新闻占满。"""
    if not CFG["sources"].get("rss"):
        return []
    feeds = CFG.get("rss_feeds") or []
    if not feeds:
        return []
    AI_RE = re.compile(
        r"(?<![a-z])(ai|gpt|claude|gemini|llm|token|api|deepseek|kimi|chatgpt|copilot"
        r"|agent|midjourney|sora|qwen|llama)(?![a-z])"
        r"|人工智能|大模型|模型|智能体|开源|豆包|通义|文心|千问", re.I)
    FREE_RE = re.compile(
        r"免费|白嫖|额度|赠送|试用|薅|羊毛|限时|优惠|折扣|免费版|免费开放|降价"
        r"|credits|free tier|for free|trial|promo|discount|open[- ]source", re.I)
    cap = int(CFG.get("rss_max_per_feed", 8))
    out = []
    for f in feeds:
        name, url = f.get("name") or url_short(f.get("url", "")), f.get("url")
        if not url:
            continue
        print(f"  · RSS {name}")
        raw = fetch(url, timeout=20)
        if not raw:
            continue
        entries = re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", raw, re.S)
        kept = 0
        for e in entries:
            t = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", e, re.S)
            title = re.sub(r"\s+", " ", (t.group(1) if t else "")).strip()
            link = re.search(r"<link[^>]*href=\"([^\"]+)\"", e) or \
                re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", e, re.S)
            url_item = (link.group(1) if link else "").strip()
            date = re.search(r"<(?:pubDate|updated|published)>([^<]+)<", e)
            desc = extract_desc(e)
            if not title or not AI_RE.search(title + " " + desc[:800]):
                continue
            if not FREE_RE.search(title + " " + desc[:1500]):
                continue
            out.append({
                "source": "rss",
                "title": title,
                "url": url_item or url,
                "meta": f"{name} · {(date.group(1) if date else '')[:16]}",
                "body": desc[:900],
            })
            kept += 1
            if kept >= cap:
                break
        print(f"    {len(entries)} 条 → 命中 {kept} 条")
    return out


def extract_desc(entry_xml):
    """取条目的正文摘要。

    不能对整个 <item> 直接去标签——多数 feed 的 description 包在
    <![CDATA[...]]> 里，`re.sub(r"<[^>]+>", " ", e)` 会把 CDATA 连同里面的
    正文一起当标签吃掉，结果是 body 全空：标题能过关键词、条目能入榜，
    但阶段2 的 LLM 看不到任何内容，只能瞎判。
    """
    for tag in ("content:encoded", "description", "summary", "content"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", entry_xml, re.S)
        if not m:
            continue
        txt = m.group(1)
        m2 = re.match(r"\s*<!\[CDATA\[(.*?)\]\]>\s*$", txt, re.S)
        if m2:
            txt = m2.group(1)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = (txt.replace("&lt;", "<").replace("&gt;", ">")
                  .replace("&quot;", '"').replace("&amp;", "&")
                  .replace("&#124;", "|").replace("&nbsp;", " "))
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        if len(txt) > 40:
            return txt
    return ""


def url_short(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return m.group(1) if m else (u or "")


def collect_openrouter():
    """OpenRouter 的免费模型目录。哪些模型刚上免费档，这里最权威；
    '上下文 1M tokens 全程 0 元'对做 AI 内容的人来说就是实打实的羊毛。"""
    if not CFG["sources"].get("openrouter"):
        return []
    cfg = CFG.get("openrouter") or {}
    days = int(cfg.get("days", 30))
    print(f"  · OpenRouter 免费模型（近 {days} 天上架）")
    raw = fetch(cfg.get("url") or "https://openrouter.ai/api/v1/models", timeout=25)
    if not raw:
        return []
    try:
        models = json.loads(raw).get("data") or []
    except Exception:
        print("    ⚠ JSON 解析失败")
        return []
    cutoff = time.time() - days * 86400
    out = []
    for m in models:
        if not str(m.get("id", "")).endswith(":free"):
            continue
        created = m.get("created") or 0
        if created < cutoff:
            continue
        ctx = int(m.get("context_length") or 0)
        ctx_txt = f"{ctx // 1000}K tokens" if ctx else "免费额度"
        name = re.sub(r"\s*\(free\)\s*$", "", m.get("name") or m.get("id", ""))
        desc = re.sub(r"<[^>]+>", " ", m.get("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        out.append({
            "source": "openrouter",
            "title": f"OpenRouter 免费模型：{name}",
            "url": f"https://openrouter.ai/{m.get('id','')}",
            "meta": f"上架 {datetime.date.fromtimestamp(created).isoformat()} · 上下文 {ctx_txt} · $0",
            "body": (desc or "免费档模型，输入输出均 0 美元")[:600],
            "sb": {
                "name": f"{name}（OpenRouter 免费档）",
                "platform": "OpenRouter",
                "benefit": f"API 免费调用，上下文 {ctx_txt}，输入输出均 $0",
                "condition": "注册 OpenRouter 即可，有每日请求次数限速",
                "deadline": None,
                "heat": 3 if ctx >= 200000 else 2,
                "confidence": "high",
                "source_url": f"https://openrouter.ai/{m.get('id','')}",
            },
        })
    print(f"    {len(out)} 条")
    return out


def collect_v2ex():
    """V2EX 的 deals / share 节点。国内羊毛（话费、会员、免费主机）比外网源更及时。
    直连被墙，走本机代理；代理没配或不通时静默跳过，不影响其他源。"""
    if not CFG["sources"].get("v2ex"):
        return []
    proxy = proxy_url()
    if not proxy:
        print("  · V2EX 跳过（pipeline.json 未配置 network.proxy）")
        return []
    AI_RE = re.compile(
        r"(?<![a-z])(ai|gpt|claude|gemini|llm|token|api|deepseek|kimi|chatgpt|copilot"
        r"|agent|midjourney|sora|qwen|llama|glm)(?![a-z])"
        r"|人工智能|大模型|智能体|豆包|通义|文心|千问", re.I)
    FREE_RE = re.compile(
        r"免费|白嫖|额度|赠送|试用|薅|羊毛|领取|限时|优惠|折扣|会员|话费|积分|credits"
        r"|free|trial|promo|discount|coupon", re.I)
    out = []
    for node in CFG.get("v2ex_nodes") or ["deals", "share"]:
        print(f"  · V2EX /{node}")
        raw = fetch(f"https://www.v2ex.com/api/topics/show.json?node_name={node}",
                    proxy=proxy, timeout=20, retries=1)
        if not raw:
            continue
        try:
            topics = json.loads(raw)
        except Exception:
            continue
        kept = 0
        for t in topics:
            title = t.get("title") or ""
            body = t.get("content") or ""
            # 标题就得写明是什么羊毛。只看正文会把「我在某站省了 20%」
            # 这种闲聊帖也算进来，正文提到优惠的讨论帖远多于真羊毛。
            if not FREE_RE.search(title):
                continue
            if not AI_RE.search(title + " " + body[:400]):
                continue
            ts = t.get("created") or 0
            out.append({
                "source": "v2ex",
                "title": title,
                "url": t.get("url") or "",
                "meta": (f"V2EX /{node} · "
                         f"{datetime.date.fromtimestamp(ts).isoformat() if ts else ''}"),
                "body": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:600],
            })
            kept += 1
        print(f"    {len(topics)} 帖 → 命中 {kept} 条")
    return out


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


def _clip(text, limit=76):
    """按标点收尾，别把话切成半句"""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in "。！？；，、":
        i = cut.rfind(sep)
        if i >= limit * 0.5:
            return cut[:i]
    return cut


PAID_TAGS = ("需付费", "订阅", "API折扣")


def _heat(d):
    """站点自己的 _rank 是编辑排序（1 最好），比我们按名称瞎猜的性价比靠谱得多。

    _rank 分位数（146 条 active）：10%→4，25%→9，50%→16，75%→41。
    付费/折扣项对"羊毛"内容是减分项——观众点进来看的是白嫖，不是省钱。
    """
    tag = d.get("_tag") or ""
    typ = d.get("type") or ""
    r = d.get("_rank")
    if r is None:
        base = 3
    elif r <= 4:
        base = 5
    elif r <= 9:
        base = 4
    elif r <= 16:
        base = 3
    elif r <= 41:
        base = 2
    else:
        base = 1
    if typ in ("折扣", "会员") or any(w in tag for w in PAID_TAGS):
        base = max(2, base - 2)
    return base


def collect_saibodan():
    """saibodan.com 的已核验福利库。

    和另外三个源完全不同：这是自己维护的数据集，每条都带 official 核验日期、
    isNew / changedToday 标记、编辑排序 _rank、类型标签 _tag。它才是"今天有什么
    新羊毛"的权威答案——AIHOT/HN/GitHub 翻来去是同一批促销加农场号。
    """
    cfg = CFG.get("saibodan") or {}
    if not CFG["sources"].get("saibodan") or not cfg.get("url"):
        return []
    print("  · saibodan.com 已核验福利库")
    raw = fetch(cfg["url"])
    if not raw:
        return []
    try:
        deals = json.loads(raw)
    except Exception:
        print("    ⚠ JSON 解析失败")
        return []
    if isinstance(deals, dict):
        deals = deals.get("deals") or deals.get("items") or []

    min_fresh = int(cfg.get("min_fresh", 3))
    max_items = int(cfg.get("max_items", 20))

    active = [d for d in deals if isinstance(d, dict) and d.get("status") == "active"]
    picked = [d for d in active if d.get("isNew") or d.get("changedToday")]
    note = "isNew/changedToday"
    if len(picked) < min_fresh:
        # 安静日没有新标记时，退回"最近有变动"的一批，仍由 02_select 的历史去重把关
        rest = [d for d in active if d not in picked]
        rest.sort(key=lambda d: str(d.get("lastChange") or ""), reverse=True)
        picked = picked + rest[:max(0, max_items - len(picked))]
        note = f"新标记不足 {min_fresh} 条，回退最近变动"

    # 按站点编辑排序输出，性价比高的排在前面
    picked.sort(key=lambda d: (d.get("_rank") if d.get("_rank") is not None else 99))

    out = []
    for d in picked:
        url = f"{cfg.get('origin', 'https://saibodan.com').rstrip('/')}/deals/{d.get('id','')}"
        elig = d.get("elig") or []
        cond = "、".join(elig) if isinstance(elig, list) else str(elig)
        # value 有时不带数字（如"每日免费 credits"），会被 has_concrete 拦掉；
        # 补上站点自己的 summary 片段，不编内容，只是把已有信息带全。
        value = _clip(d.get("value"), 120)
        benefit = value
        if not re.search(r"\d", value):
            tail = _clip(d.get("summary"))
            benefit = f"{value}：{tail}" if tail else value
        out.append({
            "source": "saibodan",
            "title": d.get("name") or "",
            "url": url,
            "meta": (f"核验 {d.get('verified','')} · {d.get('type','')} · "
                     f"{d.get('region','')} · rank {d.get('_rank','-')}"),
            "body": (d.get("summary") or value)[:600],
            # 结构化字段，02_select 直接采用，不再过一遍 LLM
            "sb": {
                "name": d.get("name") or "",
                "platform": d.get("platform") or "",
                "benefit": benefit,
                "condition": cond or "未说明",
                "deadline": d.get("expires") or None,
                "heat": _heat(d),
                "confidence": "high",
                "source_url": url,
            },
        })
    print(f"    {len(out)} 条（{note}）")
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"采集 {date}")
    items = collect_saibodan()

    # saibodan 是已核验的结构化源，条数够就不必再跑 AIHOT/GitHub/HN 三个兜底源：
    # AIHOT 翻来去是同一批促销，GitHub/HN 产出大量项目主页（本来就会被门槛筛掉），
    # 白过四轮 LLM、拖慢速度还把好条目挤下去。
    #
    # RSS / OpenRouter / V2EX 和它们不同：RSS 只放行「AI + 羊毛」双命中条目，
    # OpenRouter 直接读免费模型目录，V2EX 是纯国内羊毛帖子——产出即候选，
    # 所以不放进兜底，每天都跑。
    enough = int((CFG.get("saibodan") or {}).get("skip_fallback_if_at_least", 6))
    if len(items) >= enough:
        print(f"  saibodan 已得 {len(items)} 条（≥{enough}），跳过 AIHOT/GitHub/HN 兜底")
    else:
        print(f"  saibodan 仅 {len(items)} 条，启用 AIHOT/GitHub/HN 兜底")
        items.extend(collect_aihot())
        items.extend(collect_github())
        items.extend(collect_hn())

    items.extend(collect_rss())
    items.extend(collect_openrouter())
    items.extend(collect_v2ex())

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