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

# 绑定域名后把这里改成 https://你的域名（RSS 的绝对链接会用到）。
# 留空则站内链接全部走相对路径，本地 file:// 打开也能正常跳转。
SITE_URL = ""

# 可选：某天成片托管到哪里（B 站/网盘/对象存储），填了当日页面就会出现「看成片」入口。
VIDEO_URLS = {}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEK = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 配色取自 redesign 的封面模板，保证站和成片同一套视觉语言
CSS = """/* AI 羊毛日报 · 聚合站 */
:root{
  --bg:#0A0D13; --bg2:#0F1622; --line:#1C2434; --line2:#26314A;
  --tx:#E8EDF7; --mut:#9FB0C8; --dim:#65728A;
  --blue:#4C8DFF; --gold:#FFC53D; --org:#FF8A3D; --teal:#38E1C4;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Consolas,"Courier New",monospace;
  --sans:"Inter","HarmonyOS Sans SC","PingFang SC","Hiragino Sans GB",
         "Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--tx); font-family:var(--sans);
  line-height:1.75; font-size:16px;
  background-image:
    radial-gradient(900px 480px at 78% -10%, rgba(76,141,255,.13), transparent 60%),
    radial-gradient(700px 420px at 8% 0%, rgba(255,197,61,.07), transparent 55%);
  background-repeat:no-repeat;
}
a{color:var(--blue); text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:940px; margin:0 auto; padding:0 24px 72px}

/* 顶栏 */
.top{display:flex; align-items:center; justify-content:space-between;
  gap:16px; padding:22px 0; border-bottom:1px solid var(--line); flex-wrap:wrap}
.brand{display:flex; align-items:center; gap:10px; font-weight:800;
  letter-spacing:.02em; font-size:17px}
.brand .dot{width:9px; height:9px; border-radius:50%; background:var(--gold);
  box-shadow:0 0 14px rgba(255,197,61,.75)}
.brand small{color:var(--dim); font-weight:600; font-size:11px;
  letter-spacing:.16em; text-transform:uppercase; font-family:var(--mono)}
.nav{display:flex; gap:20px; font-size:14px; color:var(--mut); flex-wrap:wrap}
.nav a{color:var(--mut)}
.nav a:hover{color:var(--tx); text-decoration:none}

/* 头部大区 */
.hero{padding:56px 0 40px; border-bottom:1px solid var(--line)}
.eyebrow{font-family:var(--mono); font-size:12px; letter-spacing:.22em;
  text-transform:uppercase; color:var(--gold); margin:0 0 18px}
h1{margin:0; font-size:clamp(32px,6vw,58px); line-height:1.06;
  font-weight:800; letter-spacing:-.02em}
.hero .sub{margin:14px 0 0; color:var(--mut); font-size:17px; max-width:640px}
.hero .sub b{color:var(--tx); font-weight:700}
.stats{display:flex; flex-wrap:wrap; gap:14px; margin-top:34px}
.stat{background:var(--bg2); border:1px solid var(--line); border-radius:12px;
  padding:14px 20px; min-width:132px}
.stat b{display:block; font-size:26px; font-weight:800; line-height:1.2;
  font-variant-numeric:tabular-nums}
.stat span{font-size:12px; color:var(--dim); letter-spacing:.04em}
.stat.g b{color:var(--gold)} .stat.b b{color:var(--blue)}
.stat.t b{color:var(--teal)}

/* 区块标题 */
.sec{display:flex; align-items:baseline; justify-content:space-between;
  gap:16px; margin:52px 0 20px; flex-wrap:wrap}
.sec h2{margin:0; font-size:22px; font-weight:800; letter-spacing:-.01em}
.sec .en{font-family:var(--mono); font-size:11px; letter-spacing:.2em;
  color:var(--dim); text-transform:uppercase}

/* 羊毛卡片 */
.cards{display:grid; gap:14px}
.card{background:var(--bg2); border:1px solid var(--line); border-radius:14px;
  padding:20px 22px; transition:border-color .16s, transform .16s}
.card:hover{border-color:var(--line2); transform:translateY(-1px)}
.card .row1{display:flex; align-items:center; justify-content:space-between;
  gap:14px; margin-bottom:6px}
.card .idx{font-family:var(--mono); font-size:12px; color:var(--dim)}
.card h3{margin:0; font-size:19px; font-weight:800; letter-spacing:-.01em}
.card .benefit{margin:8px 0 0; color:var(--tx); font-size:15px}
.chips{display:flex; flex-wrap:wrap; gap:8px; margin-top:14px}
.chip{font-size:12px; color:var(--mut); background:rgba(255,255,255,.04);
  border:1px solid var(--line); border-radius:999px; padding:3px 11px}
.chip.dl{color:var(--org); border-color:rgba(255,138,61,.35);
  background:rgba(255,138,61,.09)}
.chip.dl.now{color:#fff; background:var(--org); border-color:var(--org);
  font-weight:700}
.card .foot{display:flex; align-items:center; justify-content:space-between;
  gap:14px; margin-top:16px; padding-top:14px; border-top:1px solid var(--line);
  font-size:13px}
.card .foot a{color:var(--blue); word-break:break-all}
.conf{font-family:var(--mono); font-size:11px; color:var(--dim);
  letter-spacing:.06em; white-space:nowrap}

/* 性价比刻度 */
.heat{display:inline-flex; align-items:center; gap:4px}
.heat i{width:7px; height:7px; border-radius:2px; background:var(--line2);
  display:block}
.heat i.on{background:var(--blue)}
.heat.s5 i.on{background:var(--gold)}
.heat.s4 i.on{background:var(--blue)}
.heat.s3 i.on{background:var(--teal)}
.heat b{font-family:var(--mono); font-size:12px; color:var(--mut);
  margin-left:5px; font-weight:600}

/* 往期 */
.archive{display:grid; gap:10px}
.arow{display:flex; align-items:center; gap:18px; background:var(--bg2);
  border:1px solid var(--line); border-radius:12px; padding:14px 18px;
  transition:border-color .16s}
.arow:hover{border-color:var(--line2); text-decoration:none}
.arow .d{font-family:var(--mono); font-size:13px; color:var(--blue);
  min-width:104px}
.arow .n{flex:1; color:var(--tx); font-size:15px; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap}
.arow .c{font-family:var(--mono); font-size:12px; color:var(--dim);
  white-space:nowrap}

/* 全库搜索 */
.search{width:100%; background:var(--bg2); border:1px solid var(--line);
  border-radius:12px; padding:13px 16px; color:var(--tx); font-size:15px;
  font-family:var(--sans); margin-bottom:16px}
.search:focus{outline:none; border-color:var(--blue)}
.search::placeholder{color:var(--dim)}
.flat{display:grid; gap:8px}
.frow{display:grid; grid-template-columns:96px 1fr auto; gap:14px;
  align-items:baseline; padding:12px 16px; background:var(--bg2);
  border:1px solid var(--line); border-radius:10px}
.frow .d{font-family:var(--mono); font-size:12px; color:var(--dim)}
.frow .t{font-size:15px}
.frow .t b{font-weight:700}
.frow .t span{color:var(--mut); font-size:13px}
.frow .h{white-space:nowrap}
.empty{color:var(--dim); font-size:14px; padding:18px 2px}

/* 翻页 */
.pager{display:flex; justify-content:space-between; gap:14px; margin-top:44px;
  padding-top:22px; border-top:1px solid var(--line); font-size:14px}
.pager a{color:var(--mut)}
.pager a:hover{color:var(--tx)}
.pager .ph{color:var(--line2)}

footer{margin-top:56px; padding-top:22px; border-top:1px solid var(--line);
  color:var(--dim); font-size:13px; display:flex; justify-content:space-between;
  gap:16px; flex-wrap:wrap}
footer code{font-family:var(--mono); font-size:12px; color:var(--mut)}

@media (max-width:640px){
  .wrap{padding:0 16px 56px}
  .hero{padding:38px 0 30px}
  .frow{grid-template-columns:1fr; gap:4px}
  .frow .h{justify-self:start}
  .arow .n{white-space:normal}
  .nav{gap:14px; font-size:13px}
}
"""


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

# 存量内容（福利库 / 攻略 / 低价 / 往期）用到的样式
CSS2 = """
/* ---------- 筛选条 ---------- */
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}
.fbtn{font:inherit;font-size:13px;color:var(--mut);background:var(--bg2);
  border:1px solid var(--line);border-radius:999px;padding:6px 14px;cursor:pointer;
  transition:color .15s,border-color .15s,background .15s}
.fbtn:hover{color:var(--tx);border-color:var(--line2)}
.fbtn.on{color:#fff;background:var(--blue);border-color:var(--blue);font-weight:600}
.fcount{font-family:var(--mono);font-size:12px;color:var(--dim);margin-left:auto;
  align-self:center}

/* ---------- 福利库卡片 ---------- */
.dgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.dcard{display:block;background:var(--bg2);border:1px solid var(--line);
  border-radius:13px;padding:16px 18px;transition:border-color .16s,transform .16s}
.dcard:hover{border-color:var(--line2);transform:translateY(-1px);text-decoration:none}
.dcard .top{display:flex;align-items:flex-start;justify-content:space-between;
  gap:10px;margin-bottom:4px}
.dcard h3{margin:0;font-size:16px;font-weight:700;line-height:1.4}
.dcard .pf{font-size:12px;color:var(--dim);margin:2px 0 8px}
.dcard .val{font-size:13px;color:var(--mut);margin:0;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.pill{font-family:var(--mono);font-size:11px;letter-spacing:.03em;color:var(--mut);
  border:1px solid var(--line);border-radius:5px;padding:2px 7px}
.pill.cn{color:var(--gold);border-color:rgba(255,197,61,.35)}
.pill.gl{color:var(--teal);border-color:rgba(56,225,196,.3)}
.pill.end{color:var(--dim);text-decoration:line-through}
.pill.soon{color:var(--org);border-color:rgba(255,138,61,.4)}

/* ---------- 详情页 ---------- */
.back{display:inline-block;font-size:13px;color:var(--mut);margin-bottom:18px}
.back:hover{color:var(--tx);text-decoration:none}
.kv{display:grid;gap:0;margin:22px 0;border:1px solid var(--line);
  border-radius:13px;overflow:hidden;background:var(--bg2)}
.kv .r{display:grid;grid-template-columns:132px 1fr;gap:16px;padding:13px 18px;
  border-bottom:1px solid var(--line)}
.kv .r:last-child{border-bottom:0}
.kv .k{font-size:13px;color:var(--dim)}
.kv .v{font-size:14px;margin:0;word-break:break-word}
.kv .v a{word-break:break-all}
.cta{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0 0}
.btn{display:inline-block;font-size:14px;font-weight:600;border-radius:10px;
  padding:11px 20px;text-decoration:none}
.btn.solid{background:var(--blue);color:#fff}
.btn.solid:hover{filter:brightness(1.1);text-decoration:none}
.btn.ghost{border:1px solid var(--line2);color:var(--mut)}
.btn.ghost:hover{color:var(--tx);text-decoration:none}
blockquote{margin:18px 0;padding:12px 18px;border-left:3px solid var(--gold);
  background:rgba(255,197,61,.06);border-radius:0 10px 10px 0;color:var(--tx);
  font-size:14px}

/* ---------- 攻略正文 ---------- */
.article{max-width:760px}
.article h2{font-size:20px;font-weight:800;margin:34px 0 12px;
  padding-bottom:8px;border-bottom:1px solid var(--line)}
.article h3{font-size:16px;font-weight:700;margin:24px 0 8px;color:var(--gold)}
.article p{margin:0 0 12px;font-size:15px;line-height:1.85}
.article ul{margin:0 0 14px;padding-left:22px}
.article li{margin:0 0 7px;font-size:15px;line-height:1.75}
.article li::marker{color:var(--blue)}
.gcard{display:block;background:var(--bg2);border:1px solid var(--line);
  border-radius:13px;padding:18px 20px;margin-bottom:12px}
.gcard:hover{border-color:var(--line2);text-decoration:none}
.gcard .no{font-family:var(--mono);font-size:12px;color:var(--gold)}
.gcard h3{margin:6px 0 4px;font-size:17px}
.gcard .lead{color:var(--mut);font-size:14px;margin:0 0 10px}
.gcard .ch{font-size:12px;color:var(--dim);margin:10px 0 0}

/* ---------- 往期速递 ---------- */
.eplist{display:grid;gap:10px}
.eprow{display:grid;grid-template-columns:104px 1fr auto;gap:16px;
  align-items:baseline;background:var(--bg2);border:1px solid var(--line);
  border-radius:12px;padding:14px 18px;transition:border-color .16s}
.eprow:hover{border-color:var(--line2);text-decoration:none}
.eprow .d{font-family:var(--mono);font-size:13px;color:var(--blue)}
.eprow .h{font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.eprow .n{font-family:var(--mono);font-size:12px;color:var(--dim);white-space:nowrap}

@media (max-width:760px){
  .dgrid{grid-template-columns:1fr}
  .kv .r{grid-template-columns:1fr;gap:4px}
  .eprow{grid-template-columns:1fr;gap:4px}
  .eprow .h{white-space:normal}
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
    return ('<span class="heat s%d" title="性价比 %d/5">%s<b>%d</b></span>'
            % (n, n, dots, n))


def deadline_chip(deadline):
    """截止时间单独成 chip；今天的截止用实心橙高亮。"""
    if not deadline:
        return ""
    today = date.today().isoformat()
    raw = str(deadline)
    urgent = (today in raw) or ("今日" in raw) or ("今天" in raw) or ("24点" in raw)
    cls = "chip dl now" if urgent else "chip dl"
    return '<span class="%s">截止 %s</span>' % (cls, esc(raw))


def condition_chip(cond):
    if not cond or str(cond).strip() in ("未说明", "无", "-"):
        return ""
    return '<span class="chip">条件 %s</span>' % esc(cond)


def card_html(item):
    name = esc(item.get("name") or "")
    benefit = esc(item.get("benefit") or "")
    src = esc(item.get("source_url") or "")
    conf = esc(item.get("confidence") or "")
    foot = ""
    if src:
        foot += '<a href="%s" target="_blank" rel="noopener">查看来源 ↗</a>' % src
    if conf:
        foot += '<span class="conf">%s</span>' % conf
    return f"""<article class="card">
  <div class="row1"><h3>{name}</h3>{heat_html(item.get("heat"))}</div>
  <p class="benefit">{benefit}</p>
  <div class="chips">{condition_chip(item.get("condition"))}{deadline_chip(item.get("deadline"))}</div>
  <div class="foot">{foot}</div>
</article>"""


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


def page(title, body, prefix=""):
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
<header class="top">
  <div class="brand"><span class="dot"></span>羊毛日报
    <small>free ai drop</small></div>
  <nav class="nav">
    <a href="{u('index.html', prefix)}">今日</a>
    <a href="{u('deals/index.html', prefix)}">福利库</a>
    <a href="{u('guides/index.html', prefix)}">攻略</a>
    <a href="{u('paid/index.html', prefix)}">低价</a>
    <a href="{u('episodes/index.html', prefix)}">往期</a>
    <a href="{u('feed.xml', prefix)}">RSS</a>
  </nav>
</header>
{body}
<footer>
  <span>数据由每日流水线自动采集、筛选、生成。</span>
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
  <p class="eyebrow">{esc(eyebrow)}</p>
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
        body += '<div class="sec"><h2>今日福利</h2><span class="en">today\'s finds</span></div>'
        body += '<div class="cards">%s</div>' % "".join(
            card_html(i) for i in t["freebies"])

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
            body += '<div class="archive">%s</div>' % "".join(
                '<a class="arow" href="%s"><span class="d">%s</span>'
                '<span class="n">%s</span></a>'
                % (u(p, ""), esc(name), esc(desc)) for p, name, desc in entries)

        if len(days) > 1:
            body += ('<div class="sec"><h2>往期</h2>'
                     '<span class="en">archive · %d 天</span></div>' % (len(days) - 1))
            body += '<div class="archive">%s</div>' % "".join(
                '<a class="arow" href="%s"><span class="d">%s</span>'
                '<span class="n">%s</span><span class="c">%d 条</span></a>'
                % (u("day/%s.html" % d["date"]), esc(d["date"]),
                   esc(d["hook"]), len(d["freebies"]))
                for d in days[1:])
    return page("羊毛日报 · 每日 AI 福利聚合", body, "")


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
    body += '<div class="sec"><h2>本期福利</h2><span class="en">%d items</span></div>' \
        % len(d["freebies"])
    body += '<div class="cards">%s</div>' % "".join(
        card_html(i) for i in d["freebies"])

    def link(other, label):
        if not other:
            return '<span class="ph">%s</span>' % label
        return '<a href="%s">%s →</a>' % (
            u("day/%s.html" % other["date"], "../"), label)

    body += ('<div class="pager">%s<a href="%s">返回今日</a>%s</div>'
             % (link(prev_d, "更新一天"), u("index.html", "../"),
                link(next_d, "更早一天")))
    return page("羊毛日报 · %s" % d["date"], body, "../")


def render_all(days):
    rows = []
    for d in days:
        for it in d["freebies"]:
            k = " ".join(str(it.get(k) or "") for k in
                         ("name", "benefit", "condition")).lower()
            rows.append(
                '<div class="frow" data-k="%s"><span class="d">%s</span>'
                '<span class="t"><b>%s</b> <span>%s</span></span>'
                '<span class="h">%s</span></div>'
                % (esc(k), esc(d["date"]), esc(it.get("name") or ""),
                   esc(it.get("benefit") or ""), heat_html(it.get("heat"))))
    body = f"""<section class="hero">
  <p class="eyebrow">all freebies</p>
  <h1>全部福利</h1>
  <p class="sub">累计 <b>{sum(len(d['freebies']) for d in days)}</b> 条，
    来自 <b>{len(days)}</b> 天。支持按产品名或福利内容搜索。</p>
</section>
<input class="search" id="q" type="search" placeholder="搜索产品名或福利内容…">
<div class="flat" id="rows">{''.join(rows) or '<p class="empty">暂无数据</p>'}</div>
<p class="empty" id="none" hidden>没有匹配的福利。</p>
<script>
(function(){{
  var q=document.getElementById('q'),rows=document.querySelectorAll('#rows .frow'),
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
    return page("全部福利 · 羊毛日报", body)


# --------------------------------------- 存量内容页面（content/ 里的）

FILTER_JS = """
(function(){
  var sel={region:'all',type:'all',status:'all'};
  var cards=[].slice.call(document.querySelectorAll('.dcard'));
  var total=cards.length;
  function apply(){
    var hit=0;
    cards.forEach(function(c){
      var ok=true;
      for(var k in sel){ if(sel[k]!=='all' && c.dataset[k]!==sel[k]) ok=false; }
      c.style.display=ok?'':'none'; if(ok)hit++;
    });
    var el=document.getElementById('cnt');
    if(el) el.textContent=hit+' / '+total+' 条';
  }
  document.querySelectorAll('.fbtn').forEach(function(b){
    b.addEventListener('click',function(){
      var g=b.dataset.g;
      document.querySelectorAll('.fbtn[data-g="'+g+'"]').forEach(function(x){
        x.classList.remove('on');
      });
      b.classList.add('on'); sel[g]=b.dataset.v; apply();
    });
  });
  apply();
})();
"""


def slug_of(url):
    """从 https://docs.saibodan.com/magpie/ 取 magpie。"""
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def region_pill(d):
    r = d.get("region")
    if r == "cn":
        return '<span class="pill cn">国内</span>'
    if r == "global":
        return '<span class="pill gl">海外</span>'
    return ""


def deal_pills(d):
    out = [region_pill(d)]
    if d.get("type"):
        out.append('<span class="pill">%s</span>' % esc(d["type"]))
    if d.get("status") == "ended":
        out.append('<span class="pill end">已结束</span>')
    elif d.get("soon"):
        out.append('<span class="pill soon">即将截止</span>')
    elif d.get("is_new"):
        out.append('<span class="pill">新上线</span>')
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
    return ('<a class="dcard" href="%s" data-region="%s" data-type="%s" '
            'data-status="%s"><div class="top"><h3>%s</h3></div>'
            '<div class="pf">%s</div><p class="val">%s</p>%s</a>'
            % (u("deals/%s.html" % d["id"], "../"), esc(d.get("region") or ""),
               esc(d.get("type") or ""), esc(d.get("status") or ""),
               esc(d.get("name") or ""), deal_subline(d),
               esc(d.get("value") or ""), deal_pills(d)))


def render_deals_index(deals):
    types = sorted({d.get("type") for d in deals if d.get("type")})

    def chip(group, value, label, on=False):
        return ('<button class="fbtn%s" data-g="%s" data-v="%s">%s</button>'
                % (" on" if on else "", group, esc(value), esc(label)))

    bar = ('<div class="filters">'
           + chip("region", "all", "全部地区", True)
           + chip("region", "cn", "国内")
           + chip("region", "global", "海外")
           + '</div><div class="filters">'
           + chip("type", "all", "全部类型", True)
           + "".join(chip("type", t, t) for t in types)
           + '</div><div class="filters">'
           + chip("status", "all", "全部状态", True)
           + chip("status", "active", "还能领")
           + chip("status", "ended", "已结束")
           + '<span class="fcount" id="cnt"></span></div>')

    body = f"""<section class="hero">
  <p class="eyebrow">freebie library</p>
  <h1>福利库</h1>
  <p class="sub">累计 <b>{len(deals)}</b> 条 AI 免费额度与限时优惠，
    按地区、类型、是否还能领筛选。</p>
</section>
{bar}
<div class="dgrid">{''.join(deal_card(d) for d in deals)}</div>
<script>{FILTER_JS}</script>"""
    return page("福利库 · 羊毛日报", body, "../")


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
    if d.get("summary"):
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
  <p class="eyebrow">{esc(d.get('platform') or 'deal')}</p>
  <h1>{esc(d.get('name') or '')}</h1>
  {ended}
</section>
<div class="kv">{''.join(r for r in rows if r)}</div>
{cta}"""
    return page("%s · 福利库" % (d.get("name") or d.get("id")), body, "../")


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
        doc = g.get("doc") or {}
        cards.append(
            '<a class="gcard" href="%s">'
            '<div class="no">%s</div>'
            '<h3>%s</h3>'
            '<p class="lead">%s</p>'
            '<ul class="ovpts">%s</ul>'
            '<p class="ch">里面讲了：%s</p></a>'
            % (u("guides/%s.html" % slug_of(g.get("url")), "../"), esc(g.get("no")),
               esc(g.get("name")), esc(g.get("lead")),
               "".join("<li>%s</li>" % esc(p) for p in g.get("points") or []),
               esc(g.get("chapters"))))
    body = f"""<section class="hero">
  <p class="eyebrow">guides</p>
  <h1>攻略</h1>
  <p class="sub">不想花钱也能用上的东西：怎么把 AI 接进工作流、怎么白嫖算力、
    新手怎么上手、副业从哪起步。<b>{len(guides)}</b> 篇。</p>
</section>
{''.join(cards)}"""
    return page("攻略 · 羊毛日报", body, "../")


def render_guide_detail(g):
    doc = g.get("doc") or {}
    art = blocks_html(doc.get("blocks"))
    body = f"""<a class="back" href="{u('guides/index.html', '../')}">← 攻略</a>
<section class="hero" style="padding:28px 0 20px">
  <p class="eyebrow">{esc(g.get('tag') or 'guide')}</p>
  <h1>{esc(g.get('name') or '')}</h1>
  <p class="sub">{esc(g.get('lead') or '')}</p>
</section>
<div class="article">{art or '<p class="empty">正文还没搬过来。</p>'}</div>"""
    return page("%s · 攻略" % (g.get("name") or slug_of(g.get("url"))), body, "../")


def render_paid(paid):
    cards = []
    for p in paid:
        cards.append(
            '<div class="gcard"><div class="no">%s</div><h3>%s</h3>'
            '<p class="lead">%s</p><ul class="ovpts">%s</ul>'
            '<p class="ch">里面讲了：%s</p></div>'
            % (esc(p.get("no")), esc(p.get("name")), esc(p.get("lead")),
               "".join("<li>%s</li>" % esc(x) for x in p.get("points") or []),
               esc(p.get("chapters"))))
    body = f"""<section class="hero">
  <p class="eyebrow">paid picks</p>
  <h1>低价订阅</h1>
  <p class="sub">在售的 AI 会员与低价开通方案。价格是当日实价，
    点开看各自能拿到什么、怎么用。<b>{len(paid)}</b> 条。</p>
</section>
{''.join(cards)}"""
    return page("低价订阅 · 羊毛日报", body, "../")


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
  <p class="eyebrow">{esc(e.get('date') or '')}</p>
  <h1>{esc(e.get('headline') or '')}</h1>
  <p class="sub">{esc(e.get('summary') or '')}</p>
</section>
{'<div class="kv"><div class="r"><div class="k">今日精选</div><div class="v"><ul style="margin:0;padding-left:20px">%s</ul></div></div></div>' % picks if picks else ''}
{''.join(secs)}"""
    return page("羊毛速递 %s" % (e.get("date") or ""), body, "../")


def render_episodes_index(eps):
    rows = []
    for e in eps:
        rows.append('<a class="eprow" href="%s"><span class="d">%s</span>'
                    '<span class="h">%s</span><span class="n">%d 条</span></a>'
                    % (u("episodes/%s.html" % e["date"], "../"), esc(e.get("date")),
                       esc(e.get("headline") or ""), len(e.get("deals") or [])))
    body = f"""<section class="hero">
  <p class="eyebrow">archive</p>
  <h1>往期速递</h1>
  <p class="sub">从 <b>{esc(eps[-1]['date']) if eps else '—'}</b> 到
    <b>{esc(eps[0]['date']) if eps else '—'}</b>，共 <b>{len(eps)}</b> 期每日羊毛速递。</p>
</section>
<div class="eplist">{''.join(rows)}</div>"""
    return page("往期速递 · 羊毛日报", body, "../")


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
    (SITE / "assets" / "style.css").write_text(CSS + CSS2, encoding="utf-8")
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
