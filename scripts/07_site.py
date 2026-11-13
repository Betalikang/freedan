#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
07_site.py · AI 羊毛日报聚合站生成器

把 runs/<日期>/ 的每日产物同步成轻量数据集 data/<日期>/（只留小 JSON，
视频/wav/截图留在 runs/ 里不进 git），再渲染成一个纯静态站点到 site/。

只用标准库，无第三方依赖、无构建步骤 —— Cloudflare Pages / Netlify 都能直接 serve。
站点根下的 `_headers`（Cloudflare Pages 响应头格式）也由本脚本生成，
所以部署侧不需要配任何 build command。

用法：
    python scripts/07_site.py             # 同步 data/ 并重建 site/
    python scripts/07_site.py --no-sync   # 只用已有 data/ 重建
"""

import sys
import json
import shutil
import html
import re
from pathlib import Path
from datetime import date, datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
DATA = ROOT / "data"
SITE = ROOT / "site"
CONTENT = ROOT / "content"   # 08_import_site.py 从 saibodan.com 搬来的存量内容

# 正式域名。RSS 的绝对链接、og 分享链接都靠它；
# 留空则站内链接走相对路径，本地双击打开也能正常跳转。
SITE_URL = "https://freedan.top"

# 可选：某天成片托管到哪里（B 站/网盘/对象存储），填了当日页面就会出现「看成片」入口。
VIDEO_URLS = {}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEK = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 配色取自 redesign 的封面模板，保证站和成片同一套视觉语言
# Cloudflare Pages 的 _headers（纯文本，不是 TOML）。
# 生成在 site/ 根下，Cloudflare 会把它应用到所有响应上。
HEADERS = """\
# AI 羊毛日报 · 由 scripts/07_site.py 生成，手改会在下次重建时被覆盖

/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()

# HTML 短缓存：改了要立刻可见
/*.html
  Cache-Control: public, max-age=0, must-revalidate

# 样式文件名不带 hash，不能长缓存 immutable，否则换设计后读者拿到旧 CSS
/assets/*
  Cache-Control: public, max-age=3600, must-revalidate

# 机器可读数据：放开跨域，方便别人二次聚合
/data/*
  Access-Control-Allow-Origin: *
  Cache-Control: public, max-age=300

/feed.xml
  Cache-Control: public, max-age=300
"""

CSS = """\n/* ============================================================
   AI 羊毛日报 · 报纸编辑风（paper editorial）
   底色用纸、正文用宋、强调用朱。不用圆角卡片盒——
   分隔靠细线和留白，像报纸而不是像 SaaS 后台。
   ============================================================ */
:root{
  --paper:#F4F0E6;
  --paper2:#FCFAF4;
  --ink:#1B1815;
  --ink2:#57514A;
  --ink3:#A29889;
  --rule:#DED6C5;
  --rule2:#C6BBA6;
  --verm:#B2390E;
  --verm-d:#8A2A08;
  --verm-l:#F4E4DA;
  --gold:#8F7328;
  --jade:#2C6B52;
  --serif:"Noto Serif SC","Source Han Serif SC","Songti SC","STSong","SimSun",Georgia,"Times New Roman",serif;
  --sans:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Consolas,"Courier New",monospace;
  --measure:37rem;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.75;
  background-image:radial-gradient(1100px 420px at 50% -8%,
    rgba(178,57,14,.055), transparent 70%);
  background-repeat:no-repeat;
}
a{color:var(--verm);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:920px;margin:0 auto;padding:0 26px 70px}

/* ---------- 报头 ---------- */
.mast{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
  padding:30px 0 14px;border-bottom:3px double var(--ink);flex-wrap:wrap}
.mast .brand{display:flex;align-items:center;gap:13px}
.mast .mark{width:32px;height:38px;flex:none;
  background:var(--verm);
  border-radius:50% 50% 50% 50%/60% 60% 42% 42%;
  position:relative;box-shadow:inset 0 -5px 0 rgba(0,0,0,.13)}
.mast .mark::after{content:"";position:absolute;left:8px;top:7px;width:8px;height:11px;
  background:rgba(255,255,255,.5);border-radius:50%}
.mast .nm{font-family:var(--serif);font-size:27px;font-weight:900;
  letter-spacing:.06em;line-height:1}
.mast .en{font-family:var(--mono);font-size:9.5px;letter-spacing:.3em;
  color:var(--ink3);text-transform:uppercase;margin-top:5px}
.mast .rt{text-align:right;font-family:var(--mono);font-size:11.5px;
  color:var(--ink2);letter-spacing:.05em;line-height:1.7}
.mast .rt b{display:block;font-family:var(--serif);font-size:15px;color:var(--ink);
  letter-spacing:.04em}

/* ---------- 导航 ---------- */
.nav{display:flex;flex-wrap:wrap;border-bottom:1px solid var(--rule)}
.nav a{font-size:14px;color:var(--ink2);padding:12px 17px;
  border-bottom:2px solid transparent;margin-bottom:-1px;letter-spacing:.03em}
.nav a:hover{color:var(--verm);text-decoration:none}
.nav a.on{color:var(--verm);border-bottom-color:var(--verm);font-weight:600}

/* ---------- 头条区 ---------- */
.hero{padding:46px 0 32px;border-bottom:1px solid var(--rule)}
.hero .kick{font-family:var(--mono);font-size:11px;letter-spacing:.22em;
  color:var(--verm);text-transform:uppercase;margin:0 0 18px}
.hero h1{font-family:var(--serif);font-size:clamp(29px,5.2vw,52px);
  line-height:1.24;font-weight:900;margin:0;letter-spacing:.015em;max-width:21em;
  text-wrap:balance;text-wrap:pretty}
.hero .sub{margin:20px 0 0;font-size:16px;color:var(--ink2);
  max-width:var(--measure);line-height:1.85}
.hero .sub b{color:var(--ink);font-weight:600;
  border-bottom:2px solid var(--verm-l);padding-bottom:1px}

/* ---------- 数据条（横排，不用盒子） ---------- */
.stats{display:flex;flex-wrap:wrap;margin:30px 0 0;border-top:1px solid var(--rule)}
.stat{padding:15px 28px 15px 0;margin-right:28px;border-right:1px solid var(--rule)}
.stat:last-child{border-right:0;margin-right:0;padding-right:0}
.stat b{display:block;font-family:var(--serif);font-size:31px;font-weight:900;
  line-height:1;color:var(--verm);font-variant-numeric:tabular-nums}
.stat span{font-size:12px;color:var(--ink3);letter-spacing:.05em}

/* ---------- 栏目标题 ---------- */
.sec{display:flex;align-items:baseline;gap:14px;margin:50px 0 2px;
  border-bottom:2px solid var(--ink);padding-bottom:9px;flex-wrap:wrap}
.sec h2{font-family:var(--serif);font-size:20px;font-weight:900;margin:0;
  letter-spacing:.03em}
.sec .en{font-family:var(--mono);font-size:10px;letter-spacing:.2em;
  color:var(--ink3);text-transform:uppercase}
.sec .rt{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--ink3)}

/* ---------- 列表行（今日福利 / 往期 / 速递共用） ---------- */
.items{display:grid}
.item{display:grid;grid-template-columns:46px 1fr auto;gap:0 20px;
  padding:21px 4px;border-bottom:1px solid var(--rule);align-items:start;
  transition:background .14s}
.item:hover{background:linear-gradient(90deg,rgba(178,57,14,.07),transparent 65%)}
.item .no{font-family:var(--serif);font-size:23px;font-weight:900;
  color:var(--verm);line-height:1.15;font-variant-numeric:tabular-nums}
.item h3{font-family:var(--serif);font-size:18px;font-weight:700;margin:0 0 6px;
  line-height:1.45}
.item .val{font-size:14.5px;color:var(--ink2);margin:0;line-height:1.75}
.item .meta{display:flex;flex-wrap:wrap;gap:9px;align-items:center;
  margin-top:11px;font-size:12px;color:var(--ink3)}
.item .src{font-size:13px;color:var(--verm);white-space:nowrap;font-weight:500}
.item .foot{grid-column:2;display:flex;align-items:center;gap:14px;
  margin-top:12px;padding-top:11px;border-top:1px dotted var(--rule2)}
.conf{font-family:var(--mono);font-size:10px;letter-spacing:.12em;
  color:var(--ink3);text-transform:uppercase;white-space:nowrap}

/* ---------- 性价比刻度 ---------- */
.heat{display:inline-flex;gap:3px;align-items:center}
.heat i{width:8px;height:8px;background:var(--rule2);display:block}
.heat i.on{background:var(--verm)}
.heat b{font-family:var(--mono);font-size:11px;color:var(--ink3);margin-left:6px}

/* ---------- 小标签 ---------- */
.tag{font-size:11.5px;color:var(--ink2);border:1px solid var(--rule2);
  padding:1px 8px;letter-spacing:.02em;line-height:1.6}
.tag.dl{color:var(--verm);border-color:var(--verm);background:var(--verm-l);
  font-weight:600}
.tag.end{color:var(--ink3);text-decoration:line-through}

/* ---------- 筛选（下划线页签，不是胶囊） ---------- */
.fbar{display:flex;flex-wrap:wrap;align-items:flex-end;gap:4px 22px;
  border-bottom:1px solid var(--rule);padding-top:6px}
.fgroup{display:flex;flex-wrap:wrap;align-items:center}
.flabel{font-family:var(--mono);font-size:10px;letter-spacing:.14em;
  color:var(--ink3);text-transform:uppercase;padding:0 10px 0 2px}
.fbtn{font:inherit;font-size:13px;color:var(--ink2);background:none;border:0;
  border-bottom:2px solid transparent;padding:10px 12px;cursor:pointer;
  letter-spacing:.02em}
.fbtn:hover{color:var(--verm)}
.fbtn.on{color:var(--verm);border-bottom-color:var(--verm);font-weight:600}
.fcount{margin-left:auto;font-family:var(--mono);font-size:11px;
  color:var(--ink3);padding-bottom:10px;white-space:nowrap}

/* ---------- 福利库（双列密排） ---------- */
.dgrid{display:grid;grid-template-columns:1fr 1fr;gap:0 38px}
.dcell{padding:13px 4px;border-bottom:1px solid var(--rule);
  transition:background .14s}
.dcell:hover{background:linear-gradient(90deg,rgba(178,57,14,.07),transparent 70%)}
.dcell .top{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.dcell h3{font-family:var(--serif);font-size:16.5px;font-weight:700;margin:0;
  line-height:1.45}
.dcell .pf{font-size:12px;color:var(--ink3);margin:5px 0 7px}
.dcell .val{font-size:13px;color:var(--ink2);margin:0;line-height:1.65;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
/* 地区/类型/状态小标签统一走 .tag， modifiers 见上面 .tag 定义处 */
.tag.gl{color:var(--jade);border-color:var(--jade)}

/* ---------- 详情页 ---------- */
.back{display:inline-block;font-size:13px;color:var(--ink2);margin:22px 0 0}
.back:hover{color:var(--verm);text-decoration:none}
.kv{display:grid;margin:26px 0 0;border-top:2px solid var(--ink)}
.kv .r{display:grid;grid-template-columns:118px 1fr;gap:20px;
  padding:15px 4px;border-bottom:1px solid var(--rule);align-items:start}
.kv .k{font-size:13px;color:var(--ink3);letter-spacing:.06em;padding-top:2px}
.kv .v{font-size:15px;margin:0;line-height:1.85;word-break:break-word}
.kv .v a{word-break:break-all}
/* 详情/往期里嵌的列表也要用站内那种朱红小方点，不能用浏览器默认圆点 */
.kv .v ul{margin:0;padding-left:0;list-style:none}
.kv .v li{position:relative;padding-left:18px;margin-bottom:8px;
  font-size:14.5px;line-height:1.8}
.kv .v li::before{content:"";position:absolute;left:2px;top:.76em;
  width:5px;height:5px;background:var(--verm)}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin:30px 0 0}
.btn{display:inline-block;font-size:14.5px;font-weight:600;padding:12px 24px;
  letter-spacing:.04em}
.btn.solid{background:var(--verm);color:#fff}
.btn.solid:hover{background:var(--verm-d);text-decoration:none}
.btn.ghost{border:1px solid var(--rule2);color:var(--ink2)}
.btn.ghost:hover{border-color:var(--verm);color:var(--verm);text-decoration:none}
blockquote{margin:0;padding:2px 0 2px 18px;border-left:3px solid var(--verm);
  font-family:var(--serif);font-size:15.5px;line-height:1.85;color:var(--ink)}

/* ---------- 攻略正文（终于有行宽和节奏了） ---------- */
.article{max-width:var(--measure)}
.article h2{font-family:var(--serif);font-size:20px;font-weight:900;
  margin:46px 0 15px;padding-left:15px;border-left:4px solid var(--verm);
  line-height:1.45;letter-spacing:.02em}
.article h3{font-family:var(--serif);font-size:16.5px;font-weight:700;
  margin:30px 0 11px;color:var(--verm-d);letter-spacing:.02em}
.article p{margin:0 0 17px;font-size:15.5px;line-height:1.95;color:var(--ink)}
.article ul{margin:0 0 20px;padding-left:0;list-style:none}
.article li{position:relative;padding-left:19px;margin-bottom:10px;
  font-size:15px;line-height:1.9}
.article li::before{content:"";position:absolute;left:2px;top:.78em;
  width:5px;height:5px;background:var(--verm)}

/* ---------- 攻略 / 低价 卡片 ---------- */
.glist{display:grid;gap:0}
.gcard{display:block;padding:22px 4px;border-bottom:1px solid var(--rule);
  transition:background .14s}
.gcard:hover{background:linear-gradient(90deg,rgba(178,57,14,.07),transparent 70%);
  text-decoration:none}
.gcard .top{display:flex;align-items:baseline;gap:14px}
.gcard .no{font-family:var(--serif);font-size:19px;font-weight:900;color:var(--verm);
  font-variant-numeric:tabular-nums}
.gcard .tag{flex:none}
.gcard h3{font-family:var(--serif);font-size:18px;font-weight:700;margin:8px 0 0}
.gcard .lead{color:var(--ink2);font-size:14.5px;margin:7px 0 0;line-height:1.75}
.gcard ul{margin:12px 0 0;padding-left:0;list-style:none}
.gcard li{position:relative;padding-left:17px;font-size:13.5px;color:var(--ink2);
  margin-bottom:5px;line-height:1.7}
.gcard li::before{content:"";position:absolute;left:2px;top:.72em;width:4px;height:4px;
  background:var(--rule2)}
.gcard .ch{font-size:12px;color:var(--ink3);margin:12px 0 0}
.gcard .ch b{color:var(--ink2);font-weight:600}

/* ---------- 往期速递 ---------- */
.eplist{display:grid}
.eprow{display:grid;grid-template-columns:108px 1fr auto;gap:18px;
  align-items:baseline;padding:16px 4px;border-bottom:1px solid var(--rule);
  transition:background .14s}
.eprow:hover{background:linear-gradient(90deg,rgba(178,57,14,.07),transparent 70%);
  text-decoration:none}
.eprow .d{font-family:var(--mono);font-size:12.5px;color:var(--verm)}
.eprow .h{font-size:14.5px;color:var(--ink);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.eprow .n{font-family:var(--mono);font-size:11.5px;color:var(--ink3);white-space:nowrap}

/* ---------- 搜索 ---------- */
.search{width:100%;background:var(--paper2);border:1px solid var(--rule2);
  border-radius:0;padding:13px 16px;color:var(--ink);font-size:15px;
  font-family:var(--sans);margin:4px 0 0}
.search:focus{outline:none;border-color:var(--verm)}
.search::placeholder{color:var(--ink3)}

/* ---------- 翻页 ---------- */
.pager{display:flex;justify-content:space-between;gap:16px;margin-top:48px;
  padding-top:20px;border-top:1px solid var(--rule);font-size:14px}
.pager a{color:var(--ink2)}
.pager a:hover{color:var(--verm)}
.pager .ph{color:var(--rule2)}

/* ---------- 报尾 ---------- */
footer{margin-top:60px;padding-top:20px;border-top:3px double var(--ink);
  color:var(--ink3);font-size:12.5px;display:flex;justify-content:space-between;
  gap:18px;flex-wrap:wrap;letter-spacing:.02em}
footer code{font-family:var(--mono);font-size:11.5px;color:var(--ink2)}

.empty{color:var(--ink3);font-size:14px;padding:20px 4px}
.more{display:block;width:100%;margin:22px 0 0;padding:14px;font:inherit;
  font-size:14px;color:var(--ink2);background:var(--paper2);
  border:1px solid var(--rule2);cursor:pointer;letter-spacing:.06em}
.more:hover{color:var(--verm);border-color:var(--verm)}

@media (max-width:720px){
  .wrap{padding:0 18px 54px}
  .hero{padding:32px 0 26px}
  .dgrid{grid-template-columns:1fr}
  .item{grid-template-columns:34px 1fr;gap:0 14px}
  .item .src{grid-column:2;margin-top:8px}
  .eprow{grid-template-columns:1fr;gap:3px}
  .eprow .h{white-space:normal}
  .kv .r{grid-template-columns:1fr;gap:4px}
  .stat{padding-right:18px;margin-right:18px}
  .mast .rt{text-align:left}
}
"""


def load_content():
    """读 content/ 下搬进来的存量内容；缺文件就当空，不阻断建站。"""
    out = {}
    for f, k in (("deals.json", "deals"), ("guides.json", "guides"),
                 ("paid.json", "paid"), ("episodes.json", "episodes")):
        p = CONTENT / f
        if not p.exists():
            out[k] = []
            continue
        try:
            out[k] = json.loads(p.read_text(encoding="utf-8")).get(k) or []
        except Exception as e:
            print(f"  ⚠ content/{f} 读失败：{e}")
            out[k] = []
    return out


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def heat_html(score):
    n = int(score or 0)
    dots = "".join('<i class="%s"></i>' % ("on" if i < n else "") for i in range(5))
    return ('<span class="heat" title="性价比 %d/5">%s<b>%d</b></span>'
            % (n, dots, n))


def deadline_chip(deadline):
    """截止时间单独成标签；今天的截止用朱红高亮。"""
    if not deadline:
        return ""
    today = date.today().isoformat()
    raw = str(deadline)
    urgent = (today in raw) or ("今日" in raw) or ("今天" in raw) or ("24点" in raw)
    return '<span class="tag%s">截止 %s</span>' % (" dl" if urgent else "", esc(raw))


def condition_chip(cond):
    if not cond or str(cond).strip() in ("未说明", "无", "-"):
        return ""
    return '<span class="tag">条件 %s</span>' % esc(cond)


def card_html(item, idx=""):
    name = esc(item.get("name") or "")
    benefit = esc(item.get("benefit") or "")
    src = esc(item.get("source_url") or "")
    conf = esc(item.get("confidence") or "")
    meta = "".join(x for x in (condition_chip(item.get("condition")),
                               deadline_chip(item.get("deadline"))) if x)
    foot = ""
    if src:
        foot += ('<a class="src" href="%s" target="_blank" rel="noopener">'
                 '查看来源 ↗</a>' % src)
    if conf:
        foot += '<span class="conf">%s</span>' % conf
    return f"""<div class="item">
  <div class="no">{idx}</div>
  <div><h3>{name}</h3><p class="val">{benefit}</p>
    <div class="meta">{meta}</div>
    <div class="foot">{foot}</div></div>
  <div>{heat_html(item.get("heat"))}</div>
</div>"""


def day_key(d):
    return d["date"]


def load_days():
    if not DATA.is_dir():
        return []
    days = []
    for d in sorted(DATA.iterdir()):
        if not d.is_dir() or not DATE_RE.match(d.name):
            continue
        fb = d / "freebies.json"
        if not fb.exists():
            continue
        try:
            freebies = json.loads(fb.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠ {d.name}/freebies.json 读取失败：{e}")
            continue
        if not isinstance(freebies, list):
            freebies = []
        content = {}
        cj = d / "content.json"
        if cj.exists():
            try:
                content = json.loads(cj.read_text(encoding="utf-8"))
            except Exception:
                content = {}
        stats = {}
        sj = d / "stats.json"
        if sj.exists():
            try:
                stats = json.loads(sj.read_text(encoding="utf-8"))
            except Exception:
                stats = {}
        meta = content.get("meta") or {}
        ov = content.get("overview") or {}
        hook = (ov.get("big_stat") or {}).get("label") or \
               (freebies[0].get("benefit") if freebies else "") or "今日 AI 福利已就绪"
        days.append({
            "date": d.name,
            "hook": hook,
            "freebies": freebies,
            "cards": (content.get("detail") or {}).get("cards") or [],
            "collected": stats.get("collected"),
            "video_seconds": stats.get("video_seconds"),
            "volume": meta.get("volume") or d.name,
            "video_url": VIDEO_URLS.get(d.name),
        })
    days.sort(key=day_key, reverse=True)
    return days


def sync_data():
    """把 runs/<日期>/ 里的小 JSON 复制成 git 友好的 data/<日期>/。"""
    if not RUNS.is_dir():
        print("  没有 runs/ 目录，跳过同步")
        return 0
    n = 0
    for d in sorted(RUNS.iterdir()):
        if not d.is_dir() or not DATE_RE.match(d.name):
            continue
        fb = d / "freebies.json"
        if not fb.exists():
            continue
        out = DATA / d.name
        out.mkdir(parents=True, exist_ok=True)
        for f in ("freebies.json", "content.json"):
            src = d / f
            if src.exists():
                shutil.copy2(src, out / f)
        # raw.json 有几十 KB，只把统计数字摘出来
        stats = {"date": d.name}
        raw = d / "raw.json"
        if raw.exists():
            try:
                stats["collected"] = len(json.loads(raw.read_text(encoding="utf-8")))
            except Exception:
                pass
        try:
            stats["qualified"] = len(json.loads(fb.read_text(encoding="utf-8")))
        except Exception:
            pass
        v = d / "video.mp4"
        if v.exists():
            stats["video_seconds"] = round(v.stat().st_size / 1e6, 2)
        (out / "stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
    return n


def u(path, prefix=""):
    """站点根相对路径 → 实际 URL。

    填了 SITE_URL 就用绝对地址（RSS 和分享链接需要）；
    没填则按页面深度加前缀：根页面 ""，day/ 页面 "../"。
    """
    if SITE_URL:
        return SITE_URL.rstrip("/") + "/" + path
    return prefix + path


NAV = [("index.html", "今日"), ("deals/index.html", "福利库"),
       ("guides/index.html", "攻略"), ("paid/index.html", "低价"),
       ("episodes/index.html", "往期"), ("all.html", "全库"), ("feed.xml", "RSS")]


def page(title, body, prefix="", nav=""):
    links = "".join(
        '<a href="%s"%s>%s</a>'
        % (u(p, prefix), ' class="on"' if p == nav else "", lbl)
        for p, lbl in NAV)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="每日 AI 免费额度、限时优惠与开源福利聚合，每天自动更新。">
<link rel="alternate" type="application/rss+xml" title="AI 羊毛日报"
      href="{u('feed.xml', prefix)}">
<link rel="stylesheet" href="{u('assets/style.css', prefix)}">
</head>
<body>
<div class="wrap">
<header class="mast">
  <div class="brand"><span class="mark"></span>
    <div><div class="nm">羊毛日报</div><div class="en">free ai drop</div></div></div>
  <div class="rt"><b>赛博鸡蛋</b>{datetime.now().strftime('%Y.%m.%d')} 刊</div>
</header>
<nav class="nav">{links}</nav>
{body}
<footer>
  <span>数据由每日流水线自动采集、筛选、生成；存量内容来自 saibodan.com。</span>
  <span>生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
</footer>
</div>
</body>
</html>"""


def stats_html(days):
    if not days:
        return ""
    today = days[0]
    total = sum(len(d["freebies"]) for d in days)
    cells = [("g", str(len(today["freebies"])), "今日福利"),
             ("b", str(len(days)), "已更新天数"),
             ("t", str(total), "累计收录")]
    if today.get("collected"):
        cells.insert(1, ("b", str(today["collected"]), "今日采集"))
    return '<div class="stats">%s</div>' % "".join(
        '<div class="stat %s"><b>%s</b><span>%s</span></div>' % (c, esc(v), esc(l))
        for c, v, l in cells)


def hero(title, eyebrow, sub, days):
    return f"""<section class="hero">
  <p class="kick">{esc(eyebrow)}</p>
  <h1>{esc(title)}</h1>
  <p class="sub">{sub}</p>
  {stats_html(days)}
</section>"""


def render_index(days, c):
    if not days:
        body = hero("还没有数据", "no data yet", "跑一次流水线就会出现在这里。", [])
    else:
        t = days[0]
        wd = WEEK[date.fromisoformat(t["date"]).weekday()]
        sub = (f'今天 <b>{len(t["freebies"])} 条</b>能直接领的 AI 福利，'
               f'按性价比排好序了。')
        body = hero(t["hook"], f'{t["date"]} · {wd}', sub, days)
        body += ('<div class="sec"><h2>今日福利</h2><span class="en">today\'s finds</span>'
                 '<span class="rt">%d items</span></div>' % len(t["freebies"]))
        body += '<div class="items">%s</div>' % "".join(
            card_html(i, "%02d" % (n + 1))
            for n, i in enumerate(t["freebies"]))

        # 存量内容入口：新站一上线就有东西可逛，不是只有今天一条
        entries = [("deals/index.html", "福利库",
                    "%d 条 AI 免费额度与限时优惠" % len(c["deals"])),
                   ("guides/index.html", "攻略",
                    "%d 篇上手与白嫖教程" % len(c["guides"])),
                   ("paid/index.html", "低价订阅",
                    "%d 条在售会员方案" % len(c["paid"])),
                   ("episodes/index.html", "往期速递",
                    "%d 期每日羊毛存档" % len(c["episodes"]))]
        entries = [e for e in entries if e[2].split(" ")[0] != "0"]
        if entries:
            body += ('<div class="sec"><h2>去逛逛</h2>'
                     '<span class="en">library</span></div>')
            body += '<div class="items">%s</div>' % "".join(
                '<a class="item" href="%s"><div class="no">→</div>'
                '<div><h3>%s</h3><p class="val">%s</p></div></a>'
                % (u(p, ""), esc(name), esc(desc)) for p, name, desc in entries)

        if len(days) > 1:
            body += ('<div class="sec"><h2>往期</h2>'
                     '<span class="en">archive · %d 天</span></div>' % (len(days) - 1))
            body += '<div class="items">%s</div>' % "".join(
                '<a class="item" href="%s"><div class="no">%s</div>'
                '<div><h3>%s</h3></div><div><span class="tag">%d 条</span></div></a>'
                % (u("day/%s.html" % d["date"]), esc(d["date"][5:]),
                   esc(d["hook"]), len(d["freebies"]))
                for d in days[1:])
    return page("羊毛日报 · 每日 AI 福利聚合", body, "", "index.html")


def render_day(d, prev_d, next_d):
    wd = WEEK[date.fromisoformat(d["date"]).weekday()]
    sub = (f'{wd} · 今日 <b>{len(d["freebies"])} 条</b>福利'
           + (f'，从 {d["collected"]} 条资讯里筛出来的。' if d.get("collected") else "。"))
    body = hero(d["hook"], d["volume"], sub, [d])
    if d.get("video_url"):
        body += ('<div class="sec"><h2>本日成片</h2><span class="en">video</span></div>'
                 '<p><a href="%s" target="_blank" rel="noopener">看本期视频 ↗</a>'
                 '（约 %s 秒）</p>'
                 % (esc(d["video_url"]), esc(d.get("video_seconds") or "—")))
    body += ('<div class="sec"><h2>本期福利</h2><span class="en">%d items</span></div>'
             % len(d["freebies"]))
    body += '<div class="items">%s</div>' % "".join(
        card_html(i, "%02d" % (n + 1))
        for n, i in enumerate(d["freebies"]))

    def link(other, label):
        if not other:
            return '<span class="ph">%s</span>' % label
        return '<a href="%s">%s →</a>' % (
            u("day/%s.html" % other["date"], "../"), label)

    body += ('<div class="pager">%s<a href="%s">返回今日</a>%s</div>'
             % (link(prev_d, "更新一天"), u("index.html", "../"),
                link(next_d, "更早一天")))
    return page("羊毛日报 · %s" % d["date"], body, "../", "index.html")


def render_all(days):
    rows = []
    for d in days:
        for it in d["freebies"]:
            k = " ".join(str(it.get(k) or "") for k in
                         ("name", "benefit", "condition")).lower()
            rows.append(
                '<div class="eprow" data-k="%s"><span class="d">%s</span>'
                '<span class="h"><b>%s</b>　%s</span>'
                '<span class="n">%s</span></div>'
                % (esc(k), esc(d["date"][5:]), esc(it.get("name") or ""),
                   esc(it.get("benefit") or ""), heat_html(it.get("heat"))))
    body = f"""<section class="hero">
  <p class="kick">all freebies</p>
  <h1>全库福利</h1>
  <p class="sub">每日流水线产出的 <b>{sum(len(d['freebies']) for d in days)}</b> 条，
    来自 <b>{len(days)}</b> 天。支持按产品名或福利内容搜索。</p>
</section>
<input class="search" id="q" type="search" placeholder="搜索产品名或福利内容…">
<div class="eplist" id="rows">{''.join(rows) or '<p class="empty">暂无数据</p>'}</div>
<p class="empty" id="none" hidden>没有匹配的福利。</p>
<script>
(function(){{
  var q=document.getElementById('q'),rows=document.querySelectorAll('#rows .eprow'),
      none=document.getElementById('none');
  q.addEventListener('input',function(){{
    var v=q.value.trim().toLowerCase(),hit=0;
    rows.forEach(function(r){{
      var ok=!v||r.dataset.k.indexOf(v)>-1;
      r.style.display=ok?'':'none'; if(ok)hit++;
    }});
    none.hidden=hit>0;
  }});
}})();
</script>"""
    return page("全库福利 · 羊毛日报", body, "", "all.html")


# --------------------------------------- 存量内容页面（content/ 里的）

FILTER_JS = """
(function(){
  var sel={region:'all',type:'all',status:'all'};
  var cells=[].slice.call(document.querySelectorAll('.dcell'));
  var BATCH=60, shown=BATCH;
  var btn=document.getElementById('more'), cnt=document.getElementById('cnt');
  function visible(){
    return cells.filter(function(c){
      for(var k in sel){ if(sel[k]!=='all' && c.dataset[k]!==sel[k]) return false; }
      return true;
    });
  }
  function paint(){
    var v=visible(), i;
    for(i=0;i<cells.length;i++) cells[i].style.display='none';
    for(i=0;i<Math.min(shown,v.length);i++) v[i].style.display='';
    var left=v.length-Math.min(shown,v.length);
    if(btn){ btn.hidden=left<=0; btn.textContent='显示剩余 '+left+' 条'; }
    if(cnt) cnt.textContent=Math.min(shown,v.length)+' / '+cells.length+' 条';
  }
  document.querySelectorAll('.fbtn').forEach(function(b){
    b.addEventListener('click',function(){
      var g=b.dataset.g;
      document.querySelectorAll('.fbtn[data-g="'+g+'"]').forEach(function(x){
        x.classList.remove('on');
      });
      b.classList.add('on'); sel[g]=b.dataset.v; shown=BATCH; paint();
    });
  });
  if(btn) btn.addEventListener('click',function(){ shown+=BATCH; paint(); });
  paint();
})();
"""


def slug_of(url):
    """从 https://docs.saibodan.com/magpie/ 取 magpie。"""
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def region_pill(d):
    r = d.get("region")
    if r == "cn":
        return '<span class="tag cn">国内</span>'
    if r == "global":
        return '<span class="tag gl">海外</span>'
    return ""


def deal_pills(d):
    out = [region_pill(d)]
    if d.get("type"):
        out.append('<span class="tag">%s</span>' % esc(d["type"]))
    if d.get("status") == "ended":
        out.append('<span class="tag end">已结束</span>')
    elif d.get("soon"):
        out.append('<span class="tag soon">即将截止</span>')
    elif d.get("is_new"):
        out.append('<span class="tag">新上线</span>')
    return '<div class="pills">%s</div>' % "".join(x for x in out if x)


def deal_subline(d):
    """平台名 + 价值指数。指数是源站的 1-10 分，不是本站的 5 分制。"""
    pf = esc(d.get("platform") or "")
    rk = d.get("rank")
    if rk:
        tag = "指数 %s" % esc(rk)
        pf = f"{pf} · {tag}" if pf else tag
    return pf


def deal_card(d):
    return ('<a class="dcell" href="%s" data-region="%s" data-type="%s" '
            'data-status="%s"><div class="top"><h3>%s</h3></div>'
            '<div class="pf">%s</div><p class="val">%s</p>%s</a>'
            % (u("deals/%s.html" % d["id"], "../"), esc(d.get("region") or ""),
               esc(d.get("type") or ""), esc(d.get("status") or ""),
               esc(d.get("name") or ""),
               deal_subline(d), esc(d.get("value") or ""), deal_pills(d)))


def render_deals_index(deals):
    types = sorted({d.get("type") for d in deals if d.get("type")})

    def chip(group, value, label, on=False):
        return ('<button class="fbtn%s" data-g="%s" data-v="%s">%s</button>'
                % (" on" if on else "", group, esc(value), esc(label)))

    def group(label, items):
        return ('<div class="fgroup"><span class="flabel">%s</span>%s</div>'
                % (label, "".join(items)))

    bar = ('<div class="fbar">'
           + group("地区", [chip("region", "all", "全部", True),
                           chip("region", "cn", "国内"), chip("region", "global", "海外")])
           + group("类型", [chip("type", "all", "全部", True)]
                   + [chip("type", t, t) for t in types])
           + group("状态", [chip("status", "all", "全部", True),
                           chip("status", "active", "还能领"),
                           chip("status", "ended", "已结束")])
           + '<span class="fcount" id="cnt"></span></div>')

    body = f"""<section class="hero">
  <p class="kick">freebie library</p>
  <h1>福利库</h1>
  <p class="sub">累计 <b>{len(deals)}</b> 条 AI 免费额度与限时优惠，
    按地区、类型、是否还能领筛。指数是源站 1-10 分的价值排序。</p>
</section>
<div class="sec"><h2>筛选</h2><span class="en">filter</span></div>
{bar}
<div class="dgrid">{''.join(deal_card(d) for d in deals)}</div>
<button class="more" id="more" hidden></button>
<script>{FILTER_JS}</script>"""
    return page("福利库 · 羊毛日报", body, "../", "deals/index.html")


def render_deal_detail(d):
    def row(k, v):
        if not v:
            return ""
        return ('<div class="r"><div class="k">%s</div>'
                '<div class="v">%s</div></div>' % (k, v))

    rows = [row("平台", esc(d.get("platform"))),
            row("能拿到", esc(d.get("value"))),
            row("条件与限制", esc(d.get("condition"))),
            row("截止", esc(d.get("deadline")))]
    if d.get("elig"):
        rows.append(row("资格要求", esc("、".join(str(x) for x in d["elig"]))))
    rows.append(row("类型", esc(d.get("type")) + " " + region_pill(d)))
    if d.get("what"):
        rows.append(row("是什么", esc(d["what"])))
    if d.get("official"):
        rows.append(row("官方原话", "<blockquote>%s</blockquote>" % esc(d["official"])))
    # 源站的 summary 常常就是 what 的截断版，重复时别占一行
    if d.get("summary") and d["summary"].strip() != (d.get("what") or "").strip():
        rows.append(row("摘要", esc(d["summary"])))
    if d.get("verified"):
        rows.append(row("核验日期", esc(d["verified"])))

    src = d.get("source_url")
    cta = ('<div class="cta">'
           '<a class="btn solid" href="%s" target="_blank" rel="noopener">去领取 ↗</a>'
           '<a class="btn ghost" href="%s">回福利库</a></div>'
           % (esc(src), u("deals/index.html", "../"))) if src else \
          ('<div class="cta"><a class="btn ghost" href="%s">回福利库</a></div>'
           % u("deals/index.html", "../"))

    ended = ('<p class="sub">这条已经结束了，留着当记录。</p>'
             if d.get("status") == "ended" else "")
    body = f"""<a class="back" href="{u('deals/index.html', '../')}">← 福利库</a>
<section class="hero" style="padding:28px 0 24px">
  <p class="kick">{esc(d.get('platform') or 'deal')}</p>
  <h1>{esc(d.get('name') or '')}</h1>
  {ended}
</section>
<div class="kv">{''.join(r for r in rows if r)}</div>
{cta}"""
    return page("%s · 福利库" % (d.get("name") or d.get("id")), body, "../",
           "deals/index.html")


def blocks_html(blocks):
    out = []
    for b in blocks or []:
        t = b.get("t")
        if t == "h2":
            out.append("<h2>%s</h2>" % esc(b.get("text")))
        elif t == "h3":
            out.append("<h3>%s</h3>" % esc(b.get("text")))
        elif t == "p":
            out.append("<p>%s</p>" % esc(b.get("text")))
        elif t == "list":
            out.append("<ul>%s</ul>" %
                       "".join("<li>%s</li>" % esc(x) for x in b.get("items") or []))
    return "".join(out)


def render_guides(guides):
    cards = []
    for g in guides:
        cards.append(
            '<a class="gcard" href="%s">'
            '<div class="top"><span class="no">%s</span>'
            '<span class="tag">%s</span></div>'
            '<h3>%s</h3>'
            '<p class="lead">%s</p>'
            '<ul>%s</ul>'
            '<p class="ch"><b>里面讲了</b>　%s</p></a>'
            % (u("guides/%s.html" % slug_of(g.get("url")), "../"), esc(g.get("no")),
               esc(g.get("tag")), esc(g.get("name")), esc(g.get("lead")),
               "".join("<li>%s</li>" % esc(p) for p in g.get("points") or []),
               esc(g.get("chapters"))))
    body = f"""<section class="hero">
  <p class="kick">guides</p>
  <h1>攻略</h1>
  <p class="sub">不想花钱也能用上的东西：怎么把 AI 接进工作流、怎么白嫖算力、
    新手怎么上手、副业从哪起步。<b>{len(guides)}</b> 篇。</p>
</section>
<div class="sec"><h2>全部攻略</h2><span class="en">{len(guides)} guides</span></div>
<div class="glist">{''.join(cards)}</div>"""
    return page("攻略 · 羊毛日报", body, "../", "guides/index.html")


def render_guide_detail(g):
    doc = g.get("doc") or {}
    art = blocks_html(doc.get("blocks"))
    body = f"""<a class="back" href="{u('guides/index.html', '../')}">← 攻略</a>
<section class="hero" style="padding:30px 0 22px">
  <p class="kick">{esc(g.get('tag') or 'guide')}</p>
  <h1>{esc(g.get('name') or '')}</h1>
  <p class="sub">{esc(g.get('lead') or '')}</p>
</section>
<div class="article">{art or '<p class="empty">正文还没搬过来。</p>'}</div>"""
    return page("%s · 攻略" % (g.get("name") or slug_of(g.get("url"))), body, "../",
           "guides/index.html")


def render_paid(paid):
    cards = []
    for p in paid:
        cards.append(
            '<div class="gcard"><div class="top"><span class="no">%s</span>'
            '<span class="tag">%s</span></div>'
            '<h3>%s</h3>'
            '<p class="lead">%s</p>'
            '<ul>%s</ul>'
            '<p class="ch"><b>里面讲了</b>　%s</p></div>'
            % (esc(p.get("no")), esc(p.get("tag")), esc(p.get("name")),
               esc(p.get("lead")),
               "".join("<li>%s</li>" % esc(x) for x in p.get("points") or []),
               esc(p.get("chapters"))))
    body = f"""<section class="hero">
  <p class="kick">paid picks</p>
  <h1>低价订阅</h1>
  <p class="sub">在售的 AI 会员与低价开通方案。价格是当日实价，
    点开看各自能拿到什么、怎么用。<b>{len(paid)}</b> 条。</p>
</section>
<div class="sec"><h2>全部方案</h2><span class="en">{len(paid)} picks</span></div>
<div class="glist">{''.join(cards)}</div>"""
    return page("低价订阅 · 羊毛日报", body, "../", "paid/index.html")


EP_FIELD_ORDER = ("changelog", "value", "howto", "condition", "deadline")
EP_FIELD_LABEL = {"changelog": "更新内容", "value": "权益", "howto": "领取路径",
                  "condition": "条件", "deadline": "截止"}


def render_episode_detail(e):
    secs = []
    for d in e.get("deals") or []:
        f = d.get("fields") or {}
        rows = []
        for k in EP_FIELD_ORDER:
            v = f.get(k)
            if v:
                rows.append("<li><b>%s：</b>%s</li>" % (EP_FIELD_LABEL[k], esc(v)))
        src = f.get("source_url")
        if src:
            rows.append('<li><b>入口：</b><a href="%s" target="_blank" '
                        'rel="noopener">%s ↗</a></li>' % (esc(src), esc(src)))
        for k, v in f.items():
            if k in EP_FIELD_ORDER or k == "source_url" or not v:
                continue
            rows.append("<li><b>%s：</b>%s</li>" % (esc(k), esc(v)))
        secs.append('<div class="kv"><div class="r"><div class="k">条目</div>'
                    '<div class="v"><b>%s</b></div></div>'
                    '<div class="r"><div class="k">明细</div><div class="v">'
                    '<ul style="margin:0;padding-left:20px">%s</ul></div></div></div>'
                    % (esc(d.get("name")), "".join(rows)))
    picks = "".join('<li><a href="%s" target="_blank" rel="noopener">%s ↗</a></li>'
                    % (esc(p.get("url")), esc(p.get("name")))
                    for p in e.get("picks") or [])
    body = f"""<a class="back" href="{u('episodes/index.html', '../')}">← 往期速递</a>
<section class="hero" style="padding:28px 0 22px">
  <p class="kick">{esc(e.get('date') or '')}</p>
  <h1>{esc(e.get('headline') or '')}</h1>
  <p class="sub">{esc(e.get('summary') or '')}</p>
</section>
{'<div class="kv"><div class="r"><div class="k">今日精选</div><div class="v"><ul style="margin:0;padding-left:20px">%s</ul></div></div></div>' % picks if picks else ''}
{''.join(secs)}"""
    return page("羊毛速递 %s" % (e.get("date") or ""), body, "../",
           "episodes/index.html")


def render_episodes_index(eps):
    rows = []
    for e in eps:
        rows.append('<a class="eprow" href="%s"><span class="d">%s</span>'
                    '<span class="h">%s</span><span class="n">%d 条</span></a>'
                    % (u("episodes/%s.html" % e["date"], "../"), esc(e.get("date")),
                       esc(e.get("headline") or ""), len(e.get("deals") or [])))
    body = f"""<section class="hero">
  <p class="kick">archive</p>
  <h1>往期速递</h1>
  <p class="sub">从 <b>{esc(eps[-1]['date']) if eps else '—'}</b> 到
    <b>{esc(eps[0]['date']) if eps else '—'}</b>，共 <b>{len(eps)}</b> 期每日羊毛速递。</p>
</section>
<div class="eplist">{''.join(rows)}</div>"""
    return page("往期速递 · 羊毛日报", body, "../", "episodes/index.html")


def render_feed(days):
    items = []
    for d in days[:30]:
        link = u("day/%s.html" % d["date"])
        names = "、".join(str(i.get("name") or "") for i in d["freebies"])
        desc = "%s（%d 条）" % (d["hook"], len(d["freebies"]))
        pub = datetime.fromisoformat(d["date"] + "T08:00:00+08:00")
        items.append(
            "<item><title>%s</title><link>%s</link><guid isPermaLink=\"true\">%s</guid>"
            "<pubDate>%s</pubDate><description>%s</description></item>"
            % (esc("羊毛日报 %s" % d["date"]), esc(link), esc(link),
               pub.strftime("%a, %d %b %Y %H:%M:%S +0800"),
               esc("%s：%s" % (desc, names))))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"><channel>'
            '<title>AI 羊毛日报</title>'
            '<link>%s</link>'
            '<description>每日 AI 免费额度、限时优惠与开源福利聚合</description>'
            '<language>zh-CN</language>%s</channel></rss>'
            % (esc(u("index.html")), "".join(items)))


def render_json(days):
    return json.dumps({
        "site": "AI 羊毛日报",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": len(days),
        "total": sum(len(d["freebies"]) for d in days),
        "freebies": [
            dict(it, date=d["date"]) for d in days for it in d["freebies"]],
    }, ensure_ascii=False, indent=1)


def main():
    if "--no-sync" not in sys.argv:
        print("同步 data/ ← runs/")
        n = sync_data()
        print(f"  {n} 天")

    days = load_days()
    print(f"读取 {len(days)} 天数据")
    if not days:
        print("没有可用数据，退出")
        return 1

    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "assets").mkdir(exist_ok=True)
    (SITE / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    (SITE / "_headers").write_text(HEADERS, encoding="utf-8")

    c = load_content()
    print(f"· 存量内容：福利库 {len(c['deals'])} / 攻略 {len(c['guides'])} / "
          f"低价 {len(c['paid'])} / 往期 {len(c['episodes'])}")

    (SITE / "index.html").write_text(render_index(days, c), encoding="utf-8")
    (SITE / "all.html").write_text(render_all(days), encoding="utf-8")
    (SITE / "feed.xml").write_text(render_feed(days), encoding="utf-8")
    (SITE / "data").mkdir(exist_ok=True)
    (SITE / "data" / "freebies.json").write_text(render_json(days), encoding="utf-8")

    ddir = SITE / "day"
    ddir.mkdir(exist_ok=True)
    for i, d in enumerate(days):
        prev_d = days[i - 1] if i > 0 else None      # 更新一天
        next_d = days[i + 1] if i + 1 < len(days) else None  # 更早一天
        (ddir / ("%s.html" % d["date"])).write_text(
            render_day(d, prev_d, next_d), encoding="utf-8")

    # ---- 存量内容 ----
    sdir = SITE / "deals"
    sdir.mkdir(exist_ok=True)
    (sdir / "index.html").write_text(render_deals_index(c["deals"]), encoding="utf-8")
    for d in c["deals"]:
        (sdir / ("%s.html" % d["id"])).write_text(render_deal_detail(d),
                                                  encoding="utf-8")

    gdir = SITE / "guides"
    gdir.mkdir(exist_ok=True)
    (gdir / "index.html").write_text(render_guides(c["guides"]), encoding="utf-8")
    for g in c["guides"]:
        (gdir / ("%s.html" % slug_of(g.get("url")))).write_text(
            render_guide_detail(g), encoding="utf-8")

    (SITE / "paid").mkdir(exist_ok=True)
    (SITE / "paid" / "index.html").write_text(render_paid(c["paid"]),
                                              encoding="utf-8")

    edir = SITE / "episodes"
    edir.mkdir(exist_ok=True)
    (edir / "index.html").write_text(render_episodes_index(c["episodes"]),
                                     encoding="utf-8")
    for e in c["episodes"]:
        (edir / ("%s.html" % e["date"])).write_text(render_episode_detail(e),
                                                    encoding="utf-8")

    total = sum(len(d["freebies"]) for d in days)
    print(f"✓ 站点已生成：{SITE}")
    for f in ("index.html", "all.html", "feed.xml", "_headers"):
        print(f"  {f:16}{(SITE / f).stat().st_size/1024:.1f} KB")
    print(f"  day/*.html        {len(days)} 页")
    print(f"  deals/*.html      {len(c['deals']) + 1} 页")
    print(f"  guides/*.html     {len(c['guides']) + 1} 页")
    print(f"  episodes/*.html   {len(c['episodes']) + 1} 页")
    print(f"  paid/index.html   1 页")
    print(f"  今日 {total} 条福利")
    return 0


if __name__ == "__main__":
    sys.exit(main())
