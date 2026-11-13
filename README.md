# AI 羊毛日报 · 每日视频流水线

每天自动抓取 AI 免费额度资讯（"羊毛"），筛出性价比最高的几条，按既定视觉风格生成一条口播视频和封面。**发布由人工完成。**

## 一条命令跑完

```bash
python scripts/run_daily.py                # 今天
python scripts/run_daily.py 2026-11-12     # 指定日期
python scripts/run_daily.py --skip-render  # 只到写稿，不出片
```

产物全部落在 `runs/<日期>/`：

| 文件 | 说明 |
|---|---|
| `raw.json` | 阶段1 采集的原始资讯（AIHOT + GitHub + HN） |
| `freebies.json` | 阶段2 筛出的合格羊毛 |
| `content.json` | 阶段3 生成，时间轴由阶段4 按真实音频重写（含 `detail.cues`） |
| `sentences.json` | 口播稿（完整句子，非字幕碎片） |
| `narration.wav` | 阶段4 整段合成的配音 |
| `timings.json` | 字级边界 + 语音起止点 + 字幕条 |
| `script.md` | 人工可读的发布文案，含来源链接 |
| `publish.md` | **发布用文案**：标题候选、正文、置顶评论、话题标签、发布建议 |
| `video.mp4` | 成片 |
| `cover_16x9.png` | 封面 1920×1080 |
| `cover_4x3.png` | 封面 1600×1200 |
| `cover_3x4.png` | 封面 1080×1440 |

## 七个阶段

```
[1/7] 01_collect.py   多信源采集，按标题去重
[2/7] 02_select.py    LLM 提取「能拿到什么/条件/截止」+ 硬门槛过滤
[3/7] 03_compose.py   写文案、拼卡片，产出 content.json（时间轴此时是估值）+ publish.md
[4/7] 04_narrate.py   整段一次合成配音 + 字级时间戳 → 用真实音频重写时间轴
[5/7] 05_render.py    按 cues 切片段渲染画面 → 拼接 → 铺音轨
[6/7] 06_cover.py     套封面模板换数据
[7/7] 07_site.py      把当日数据并进聚合站（data/ + site/）
```

第 7 步只重建站点、不推送；推送到 GitHub 由 `deploy_site.py` 单独负责。

### 阶段2 的两道硬门槛

LLM 会自由发挥，所以除了提示词约束，代码层还有两道闸：

- `has_concrete()` —— 福利描述里必须出现数字，或含"长期/永久/不限量/无限"，否则是空话
- `is_homepage_or_listing()` —— URL 路径段 ≤3 的（首页）或标题含"清单/列表/合集/directory"的，判为无法当日核验，剔除

今天合格羊毛不足时（低于 `min_items_for_video`），流水线**返回 0 而不是报错**，只在 `runs/<日期>/freebies.json` 留下采集数据，不出片。

## 关键设计

**口播整段一次合成，不逐句合成。** 每句单独合成时，TTS 会为每个 utterance 重新起音、重新落调、句末还给一个完整停顿——10 句拼起来就是 10 段独立录音的听感，一顿一顿，即使语速完全统一也不像人话。整段合成让语调跨句连续流动。代价是必须先出音、后定时间轴，所以拆出了 `04_narrate.py` 这一阶段：`03_compose` 先按字数估一个时间轴，`04_narrate` 拿到真实音频后再重写它。

**时间戳来自 TTS 引擎本身，不用 Whisper。** `edge_tts.Communicate(..., boundary="WordBoundary")` 会在流里吐出每个词的精确 `offset`/`duration`（100ns 单位），语音起止点和字幕条都由它算。试过 Whisper：`base` 模型会把 "Higgsfield" 听成 "K-Sleep"、"tokens" 听成 "Tocans"，字幕直接全错；`find_alignment` 强制对齐倒是能用，但要处理 30 秒 mel 窗口和 DTW 回退，远比一个参数麻烦。

**字幕条按标点切原文，不按词切。** WordBoundary 的词文本不含标点，直接在词上断句会导致 26-32 字一条、每条 5 秒，没法看。但词的规范化拼接与原文规范化完全一致，所以先按标点把原文切成 ≤16 字的片，再把每片的字符区间映射回词的时间戳。成品约 17 条、每条 0.6-4.9 秒。硬切时会回退到最近的空格，不会把 "Seedance" 断成 "See"。

**字幕走 `.cap`，不烧 libass。** `build_segments` 按 `detail.cues` 切分时间片段，把字幕文本渲染进 `.cap`（bottom 34px，34px 字号）。这样字幕和版式同一套字体和阴影，也避开了 Windows 上 libass 选中文字体的坑。

**钩子在封面里就开讲，前 5 秒不留死白。** 短视频平台前 1-3 秒决定完播率，所以配音起点是 `AUDIO_OFFSET = 0.5s`（封面内），而不是等详情段。第一句口播就是钩子：10-16 字、2-3 秒说完、必须同时有具体数字和不做的代价，禁止寒暄和自我介绍了——这条规范写在 `03_compose.py` 的 `COPY_PROMPT` 里，兜底模板也照此写。封面的 `.picks` 条因此上移到 `bottom:104px`，给 `.cap` 让位。

**时间轴结构：**

```
封面 0-1s（钩子起） → 概览 1-4s（钩子续） → 详情 4-55.8s（正文+字幕） → 清单 55.8-（静音）
```

详情段结束于「语音真实终点 + 0.7s 收尾」，清单页每页 5 秒。配音按 `audio_offset` 原样铺入，**不做任何变速拉伸**。

**音画同步只有一个源头。** `apply_timings()` 把 `audio_offset` 写进 `timeline`，字幕偏移量算作 `audio_offset - speech_start`，而 `05_render.build_track()` 铺音轨也用同一个 `tl["audio_offset"]`。早期版本这两处各算各的（一个用 `detail_start + lead`，一个用 `detail_start`），字幕整体比人声慢 0.35 秒——改任意一处都会重新引入这个 bug，所以两边必须同源。

**BGM 铺在底层，人声侧链闪避。** 音乐来自 `assets/bgm.wav`（从 `dl.mp4` 的 101.4-146s 纯音乐段抽出，原片解说 101.38s 结束，之后是纯 BGM）。文件缺失时会自动从 `source_video` 重抽；源视频也没有就降级为纯人声并打警告，不会让流水线挂掉。

混音链路（`05_render.mix_bgm()`）：

```
BGM → acrossfade 自环到成片长度（2s 交叉淡化，消循环接缝）
    → highpass 110Hz（原片是低码率 AAC，20-80Hz 占了 20% 能量，手机喇叭听不到还吃余量）
    → afade 入 0.8s / 出 2.5s
    → volume -6dB
    → sidechaincompress（人声作侧链：说话压低、停口回升）
    → amix + alimiter 0.95
```

实测配比：人声下 BGM 被压低到 -36.8dB（低于人声 18.4dB），清单段无人声时回到 -29.9dB。峰值 -1.0dBFS，无削波。`sidechaincompress` 的 `threshold`/`ratio`/`attack`/`release` 和音量都在 `config.json` 的 `video.bgm` 里可调。

**复用而非复制。** `05_render.py` / `06_cover.py` 直接 import `E:\saibodan\redesign\scripts` 下的 `build_slides`、`render_video`、`render_slides`。改视觉风格请改 `redesign/`，不要改这里。

**封面模板用 `{{TOKEN}}` 占位符，不做逐字字符串替换。** 模板在 `redesign/html/cover_{16x9,4x3,3x4}.html`，数据节点写成 `{{TITLE}}`、`{{S1_NUM}}` 这样的占位符；`05_cover.py` 的 `token_map()` 从 `content.json` 生成一份字典统一填。替换完会正则扫一遍，**只要有占位符没填上就直接报错**，不会静默出半张错图。

（早期版本是 `html.replace("赛博鸡蛋", title)` 这种逐字替换，漏了三个字段没被发现——stat-label 一直显示模板原作者的产品名，3:4 的清单数一直是 125。占位符 + 残留检查就是为了杜绝这类问题。）

新增比例：在 `redesign/html/` 加一个 `cover_<比例>.html`，再到 `05_cover.py` 的 `TEMPLATES` 列表里加一行 `(模板名, 输出名, 宽, 高)` 即可。

## 改配置

`config.json`：

- `sources` —— 四个信源开关，任何一个挂掉不影响其他
- `search_queries` —— AIHOT 搜索词
- `thresholds.min_items_for_video` —— 低于这个数不出片（默认 2）
- `thresholds.max_detail_cards` —— 详情卡上限（默认 3）
- `thresholds.min_heat` —— 性价比评分下限（默认 2）
- `publish.hashtags` —— 发布文案的话题标签
- `publish.cta` —— 正文末尾的引流句
- `video.voice` / `video.rate` / `video.pitch` —— 配音音色、语速、音高。`rate` 直接影响成片时长（+5% ≈ 59s 口播 → 70s 成片）
- `paths.redesign` —— 版式脚本位置
- `paths.skill_scripts` —— LLM 客户端位置（复用 video-style-analysis 的 `llm_analyzer`）

## 换声线

```bash
python -c "import asyncio,edge_tts;[print(v['ShortName'],v['Gender'],v.get('VoiceTag',{}).get('VoicePersonalities')) for v in asyncio.run(edge_tts.list_voices()) if v['Locale'].startswith('zh-CN')]"
```

现成可用的几个：

| 声线 | 特点 |
|---|---|
| `zh-CN-XiaoxiaoNeural` | 女声，温暖，当前默认 |
| `zh-CN-XiaoyiNeural` | 女声，活泼 |
| `zh-CN-YunxiNeural` | 男声，阳光活泼，适合快节奏口播 |
| `zh-CN-YunyangNeural` | 男声，专业可靠 |

改 `config.json` 的 `video.voice` 后重跑 `python scripts/run_daily.py <日期>`，配音和出片会重新生成。

**别用 SSML。** 在这个端点上 `<prosody rate="+21%">` 反而比纯文本 +0% 还慢一倍，`<voice>` 包裹后慢 4 倍，`mstts:express-as` 的风格指令让时长涨 4 倍且不可控。`Communicate` 的 `rate`/`pitch` 参数可靠，SSML markup 不可靠。

## 定时

已注册每日定时任务 `ai-freebie-daily-video`，每天 08:09 自动跑。手动补跑某一天：

```bash
python scripts/run_daily.py 2026-11-13
```

## 聚合网站

除了视频，同一批数据还会渲染成一个纯静态聚合站，推到 GitHub 后由 Cloudflare Pages 发布。

```bash
python scripts/07_site.py               # 只重建站点，不动 git
python scripts/deploy_site.py           # 重建 + 提交 + 推送
python scripts/deploy_site.py --dry-run # 只重建
```

产物在 `site/`：

| 文件 | 说明 |
|---|---|
| `index.html` | 今日福利 + 统计 + 往期入口 |
| `day/<日期>.html` | 单日页面，可前后翻页 |
| `all.html` | 全部历史福利，带前端搜索框 |
| `feed.xml` | RSS，可直接订阅 |
| `data/freebies.json` | 机器可读全量数据，已开 CORS |
| `assets/style.css` | 样式，配色取自 `redesign` 的封面模板 |
| `_headers` | Cloudflare Pages 响应头（安全头 + 分级缓存），由脚本生成 |

站点读的是 `data/<日期>/`（`07_site.py` 从 `runs/<日期>/` 同步过来的小 JSON）；
`runs/` 整个目录被 `.gitignore` 忽略，视频和音频不进仓库。

`07_site.py` 只用标准库、无第三方依赖、无构建步骤，Cloudflare Pages 直接 serve `site/`，
所以部署侧的 **build command 是空的** —— 不依赖 Cloudflare 的 Python 环境，
也就不存在"构建挂了站点悄悄停更"。响应头走 `site/_headers`（Cloudflare 原生格式），
同样由脚本生成，部署侧不用配。

**绑定域名后**，把 `scripts/07_site.py` 顶部的 `SITE_URL` 改成 `https://你的域名`，
RSS 的绝对链接才会指向正式地址。留空则站内链接走相对路径，本地双击打开也能正常跳转。

### 上线三步（人工做一次）

1. **建仓库** —— 在 github.com 新建一个**空**仓库（不要勾选 README / .gitignore），然后：

   ```bash
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   python scripts/deploy_site.py
   ```

   首次 push 会弹 Git Credential Manager 的浏览器授权，通过一次就长期生效。

2. **连 Cloudflare Pages** —— Cloudflare  Dashboard → Workers & Pages → Create → Pages →
   Connect to Git → 授权 GitHub 后选这个仓库。**Build command 留空**，
   Build output directory 填 `site`，Root directory 留空。之后每次 push 自动部署。

3. **绑域名** —— 项目 → Custom domains → Set up a domain：
   - **根域名**（`example.com`）：必须把域名的 NS 改到 Cloudflare（Full setup），
     然后在 DNS 里加一条 `example.com` → `<项目名>.pages.dev` 的 CNAME（Cloudflare 会
     自动 flatten，不需要 A 记录）。
   - **子域名**（`www.example.com`）：CNAME 指向 `<项目名>.pages.dev` 即可，
     用不上改 NS 的 Partial（CNAME setup）也行。
   - 证书由 Cloudflare 自动签，等几分钟转 Active。

> 国内访问比 Netlify 稳，但不保证全程畅通。Cloudflare 的 Anycast 在大陆偶尔会被绕到
> 丢包节点，这是免费方案的固有现象；真要稳得上企业版或换国内 CDN。
> 换到 Netlify / Vercel 也行 —— `site/` 是纯静态的，只改这三步，生成器和数据不用动。

## 已知边界

- AIHOT 的"羊毛"内容本身很稀薄（实测今天 13 条里 0 条纯羊毛），主要靠 GitHub/HN 兜底
- GitHub/HN 抓到的多是项目主页，会被可核验门槛筛掉，所以最终入选条数波动大
- LLM 生成失败时会退到 `fallback_content()` 结构化兜底模板，画面不会空，但文案会比较干
- 取不到 WordBoundary 时（edge-tts 版本或服务变动）会按字数比例兜底：字幕条数和时间会变粗，但文字不会错
