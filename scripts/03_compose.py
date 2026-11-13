#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段3：把选出的羊毛写成视频所需内容

产出：
  content.json      —— 直接喂给 redesign 的版式生成器
  sentences.json    —— 口播稿（完整句子）
  script.md         —— 人工可读的发布文案
"""

import sys
import os
import json
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


COPY_PROMPT = """你要为一条 AI 羊毛速递短视频写内容。风格：干脆、口语、信息密度高、不说废话。

## 今天的羊毛
{items}

## 只输出一个 JSON 对象，结构如下
{{
  "title": "视频主标题，4-6 字，有辨识度，例如 今日羊毛 / 白嫖速递",
  "title_en": "英文副标，全大写，2-3 个词",
  "tagline": "一句话概括今天最值得拿的，20 字以内，必须具体",
  "coverage": "一句补充，说明数量或范围，20 字以内",
  "cards": [
    {{
      "name": "产品名",
      "headline": "能拿到什么，20 字以内，带数字",
      "body": "60-100 字，讲清楚是什么、能拿多少、什么条件、什么时候截止",
      "tags": ["最多3个短语标签"],
      "stat": "右侧大数字，只填数字或极短词，如 3天 / 30天 / 5折",
      "stat_label": "大数字的说明，如 免费不限量"
    }}
  ],
  "sentences": ["钩子句", "完整句子2"]
}}

## 规则
- cards 取性价比最高的最多 3 条，按价值从高到低
- sentences 写 8-10 句口播稿：第 1 句是钩子，中间每 1-2 句讲一个福利，最后 1 句收尾
- 钩子是全文最重要的一句：10-16 字，2-3 秒说完，必须同时有具体数字和不做的代价。
  禁止寒暄、禁止自我介绍、禁止"大家好""今天给大家""随着AI发展"这类开头。
  合格示例：「三个大厂今天集体送钱」「这波免费额度今晚就过期」
- 其余每句 15-40 字，标点完整，必须是完整句子（不是字幕碎片）
- 所有数字必须来自素材，不要编造
- 不要输出解释文字，不要 markdown 围栏"""

SCRIPT_PROMPT = """# 同上，用于单独的二次调用（保留作为备用）"""


def call(prompt, tokens=20000):
    return L.call_llm([{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                      max_tokens=tokens)


def merge_same_subject(items):
    """同一产品的多条合并，保留 heat 最高的表述"""
    groups = {}
    for it in items:
        key = it["name"].split("（")[0].strip().lower()
        if key in groups:
            cur = groups[key]
            cur["benefit"] = cur["benefit"] + "；" + it["benefit"]
            if it["heat"] > cur["heat"]:
                cur["heat"] = it["heat"]
        else:
            groups[key] = dict(it)
    return sorted(groups.values(), key=lambda x: -x["heat"])


def fallback_content(items, date):
    """LLM 失败时的兜底：直接用结构化数据拼"""
    cards = []
    for it in items[:3]:
        cards.append({
            "name": it["name"],
            "headline": it["benefit"][:22],
            "body": f"{it['benefit']}。{it['condition']}。" +
                    (f"截止 {it['deadline']}。" if it.get("deadline") else ""),
            "tags": [t for t in (it["condition"][:8],) if t],
            "stat": "免费",
            "stat_label": it["name"][:10],
        })
    return {
        "title": "今日羊毛",
        "title_en": "FREE AI FINDS",
        "tagline": items[0]["benefit"][:24] if items else "",
        "coverage": f"今天 {len(items)} 条可用福利",
        "cards": cards,
        "sentences": [f"{len(items)} 条免费额度，过期就没了。"] +
                     [f"{it['name']}：{it['benefit']}。" for it in items[:5]] +
                     ["链接都在简介，先去领。"],
    }


def build_content(items, date):
    payload = json.dumps(items, ensure_ascii=False, indent=1)
    try:
        out = call(COPY_PROMPT.format(items=payload))
        data = L.extract_json(out)
        if not isinstance(data, dict) or not data.get("cards"):
            raise ValueError("返回结构不完整")
        if not data.get("sentences"):
            raise ValueError("缺少口播稿")
        return data
    except Exception as e:
        print(f"  ⚠ LLM 生成失败（{e}），使用兜底模板")
        return fallback_content(items, date)


def to_video_content(data, items, date):
    """转成 redesign 的 content.json 结构"""
    d = datetime.date.fromisoformat(date)
    cards = data["cards"][:3]
    n = len(cards)

    detail_cards = []
    accents = ["gold", "blue", "gold"]
    for i, c in enumerate(cards):
        detail_cards.append({
            "idx": f"{i+1:02d}",
            "accent": accents[i % 2],
            "title": c["name"],
            "body": "**" + c["headline"] + "**，" + c["body"],
            "tags": [{"text": t, "style": ("on" if j == 0 else "")}
                     for j, t in enumerate(c.get("tags", [])[:3])],
            "side": {
                "label": c.get("stat_label", "能拿到"),
                "num": c.get("stat", "免费"),
                "unit": "",
                "note": c["headline"],
                "num_style": "blue" if i % 2 else "",
            },
        })

    # 清单页：剩余条目 + 全部条目做索引
    lists = []
    if len(items) > n:
        rest = items[n:]
        per_page = 16
        for p in range(0, len(rest), per_page):
            chunk = rest[p:p + per_page]
            lists.append({
                "section": "还能领的", "total": len(rest),
                "page": f"{p//per_page+1}/{max(1,(len(rest)+per_page-1)//per_page)}",
                "items": [{"name": it["name"], "desc": it["benefit"][:40]} for it in chunk],
            })

    # 时间轴：封面 1s → 概览 4s → 详情（承载口播）→ 清单
    OVERVIEW_DUR = 4.0
    detail_start = 1.0 + OVERVIEW_DUR
    # 口播时长估算：约 4.6 字/秒
    import re as _re
    n_chars = sum(len(_re.findall(r"[一-鿿]", s)) for s in data.get("sentences", []))
    speak_dur = max(18.0, n_chars / 4.6 + 2.0)
    detail_end = detail_start + speak_dur
    list_start = detail_end
    list_dur = 5.0 * max(1, len(lists))
    total = list_start + list_dur if lists else detail_end

    return {
        "meta": {
            "brand": CFG["brand"]["name"], "brand_en": CFG["brand"]["en"],
            "volume": f"{d.year} · {d.month}月{d.day}日", "badge": f"{len(items)} 条可用福利 · 今日核验",
            "date": f"{d.year}.{d.month:02d}.{d.day:02d}",
            "title": data["title"], "title_en": data.get("title_en", "FREE AI FINDS"),
            "edition": f"{d.month}月{d.day}日 速递",
            "domestic": len(items), "foreign": None, "total": len(items),
        },
        "timeline": {
            "total_duration": round(total, 2),
            "cover": {"start": 0.0, "end": 1.0},
            "overview": {"start": 1.0, "end": detail_start},
            "detail": {"start": detail_start, "end": detail_end},
            "list_start": list_start,
            "list_page_dur": 5.0,
        },
        "cover": {
            "eyebrow": "今日羊毛",
            "picks": [{"tag": "本期重点", "name": c["name"][:18],
                       "note": c["headline"][:20], "accent": "gold" if i == 0 else "blue"}
                      for i, c in enumerate(cards[:2])],
        },
        "overview": {
            "title_prefix": "今天值得拿的", "count": n, "title_suffix": "条",
            "big_stat": {"label": data.get("tagline", "")},
            "count_line": {"label": "本期清单", "value": len(items),
                           "note": "条 · " + data.get("coverage", "")},
            "verified": f"数据核验 {d.isoformat()}",
            "right_list": [{"idx": f"{i+1:02d}", "name": c["name"][:18],
                            "sub": c["headline"][:18], "note": c["headline"][:14]}
                           for i, c in enumerate(cards)],
        },
        "detail": {
            "section": {"prefix": "今天值得拿的", "count": n, "suffix": "条",
                        "en": "TODAY'S FINDS"},
            "cards": detail_cards,
            "cues": [],
        },
        "lists": lists,
    }


def _brief(text, n=58):
    """截到 n 字。优先在最早的句读处断——句子完整比塞满更重要。"""
    t = " ".join(str(text or "").split())
    if len(t) <= n:
        return t
    cut = t[:n]
    for sep in ("；", "。", "，"):
        i = cut.find(sep)
        if 12 <= i <= n - 6:
            return cut[:i].rstrip(" ，。；")
    i = cut.rfind(" ")
    return cut[:i].rstrip() if i >= 12 else cut


def _match_item(card_name, items):
    """把 LLM 写的卡片名匹配回原始条目（LLM 会改写成更短的说法）"""
    best, score = None, 0
    for it in items:
        s = len(os.path.commonprefix([it["name"].lower(), card_name.lower()]))
        if s > score:
            best, score = it, s
    return best if score >= 2 else None


def build_publish(items, data, date):
    """生成发布文案：标题候选 + 正文 + 置顶评论 + 话题标签"""
    cards = data.get("cards", [])[:3]
    sentences = data.get("sentences", [])
    hook = sentences[0] if sentences else ""
    pub = CFG.get("publish", {})

    # 视频里讲过的排前面，保持文案与成片顺序一致
    ordered, used = [], set()
    for c in cards:
        it = _match_item(c.get("name", ""), items)
        if it and id(it) not in used:
            ordered.append(it)
            used.add(id(it))
    ordered += [it for it in items if id(it) not in used]

    lead = cards[0] if cards else {}
    titles = [
        f"今天的 AI 羊毛：{_brief(lead.get('headline', ''), 16)}",
        f"{len(items)} 个 AI 白嫖额度，今天都能领",
        hook or f"今天的 AI 羊毛，{len(items)} 条能领",
    ]

    lines = [
        f"# 发布文案 · {data.get('title', '今日羊毛')} {date}", "",
        "## 标题（三选一）", "",
    ]
    for i, t in enumerate(titles, 1):
        lines.append(f"{i}. {t}")
    lines += ["", "> 建议用 1：数字具体、和视频开头钩子呼应。", "", "## 正文", "",
              f"今天的 AI 羊毛整理好了，{len(items)} 条都能领。", ""]
    for i, it in enumerate(ordered, 1):
        note = _brief(it["benefit"])
        dl = it.get("deadline")
        # 截止已经写在福利里就别重复一遍
        if dl and dl not in it["benefit"]:
            note += f"（{dl} 截止）"
        lines.append(f"{i}. {it['name']} — {note}")
    dls = [f"{it['name']} {it['deadline']}" for it in ordered if it.get("deadline")]
    if dls:
        lines += ["", "注意 " + "、".join(dls) + " 截止，要用的赶在前。"]
    lines += ["", pub.get("cta", "链接在评论区置顶。"), "", "## 置顶评论", "",
              "领取入口（按视频顺序）：", ""]
    for i, it in enumerate(ordered, 1):
        lines.append(f"{i}. {it['name']}：{it.get('source_url', '—')}")
    tags = " ".join(f"#{t}" for t in pub.get("hashtags", []))
    lines += ["", "## 话题标签", "", tags, "", "## 发布建议", "",
              "- 时间：早 8-9 点或晚 8-10 点（本片目标观众是上班族和开发者）",
              "- 封面用 `cover_3x4.png`（竖版 3:4，信息流占位最大）；横版场景用 `cover_16x9.png`",
              f"- 前 3 秒是钩子「{hook}」，发布后别裁剪开头", ""]
    # 只标可能花钱的：条件里明说绑卡未说明的
    risky = [it["name"] for it in ordered
             if "绑卡" in (it.get("condition") or "")
             and "未说明" in (it.get("condition") or "")]
    if risky:
        lines += ["## 备注", "",
                  "- 以下条目未说明是否要绑卡，领取前自己确认一下：" + "、".join(risky), ""]
    return "\n".join(lines)


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    items = json.loads((run_dir / "freebies.json").read_text(encoding="utf-8"))
    if len(items) < CFG["thresholds"]["min_items_for_video"]:
        print(f"✗ 合格羊毛仅 {len(items)} 条，低于门槛 {CFG['thresholds']['min_items_for_video']}，不出片")
        return 3

    items = merge_same_subject(items)
    print(f"合并同主体后 {len(items)} 条")

    print("生成文案...")
    data = build_content(items, date)

    content = to_video_content(data, items, date)
    (run_dir / "content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")

    sentences = data.get("sentences", [])
    (run_dir / "sentences.json").write_text(
        json.dumps({"sentences": sentences}, ensure_ascii=False, indent=1), encoding="utf-8")

    md = [f"# {content['meta']['title']} · {date}", "",
          f"**{data.get('tagline','')}**", "", "## 本期羊毛", ""]
    for i, it in enumerate(items, 1):
        md.append(f"{i}. **{it['name']}** — {it['benefit']}")
        md.append(f"   - 条件：{it['condition']}　截止：{it.get('deadline') or '—'}　性价比：{it['heat']}/5")
        if it.get("source_url"):
            md.append(f"   - 来源：{it['source_url']}")
        md.append("")
    md += ["## 口播稿", ""] + [f"- {s}" for s in sentences]
    (run_dir / "script.md").write_text("\n".join(md), encoding="utf-8")

    (run_dir / "publish.md").write_text(
        build_publish(items, data, date), encoding="utf-8")

    print(f"✓ 内容已生成")
    print(f"  标题: {content['meta']['title']}")
    print(f"  卡片: {len(content['detail']['cards'])} 张")
    print(f"  口播: {len(sentences)} 句")
    print(f"  清单页: {len(content['lists'])} 页")
    print(f"  时长: {content['timeline']['total_duration']}s")
    print(f"  发布文案: {run_dir / 'publish.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())