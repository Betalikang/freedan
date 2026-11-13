#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间轴与字幕的公共计算。

配音改成"整段一次合成"之后，视频时长不再由字数估算，而是由真实音频决定。
本模块提供两件事：
  build_cues()      —— 由已知文案 + 字级时间戳生成字幕条
  apply_timings()   —— 用真实语音起止点重写 content.json 的时间轴
"""

import re
import json

# 句末标点：必须断开
END_PUNCT = "。！？；!?;"
# 句中标点：长度够了就在这里断
MID_PUNCT = "，、,"

MAX_CUE_CHARS = 16      # 单条字幕目标字数（.cap 为 34px 单行，1920 宽约可容 50 字）
HARD_MAX_CHARS = 24     # 超过这个长度即使没有标点也强制断
MIN_CUE_DUR = 0.7       # 短于此时长与相邻条合并
MAX_CUE_DUR = 5.0

AUDIO_OFFSET = 0.5      # 配音铺入时间轴的起点：封面内就开讲，不留死白
COVER_DUR = 1.0         # 封面时长
OVERVIEW_DUR = 3.0      # 概览时长
TAIL = 0.7              # 语音结束后的收尾

_NORM = re.compile(r"[^\w一-鿿]")


def _norm(s):
    return _NORM.sub("", s)


def _clean(text):
    """去掉首尾空白和难看的标点；句末标点保留，读起来有完结感"""
    t = text.strip().strip("　 ")
    t = re.sub(r"^[，、,。！？；]+", "", t)
    return t.rstrip("，、, ").strip()


def _split_pieces(text, max_chars, hard_max):
    """按标点把全文切成字幕片；返回 (片文本, 规范化起点, 规范化终点)"""
    pieces = []
    buf, buf_start, cur = "", 0, 0
    for ch in text:
        buf += ch
        cur += len(_norm(ch))
        blen = cur - buf_start
        force = blen >= hard_max
        if not (ch in END_PUNCT or (ch in MID_PUNCT and blen >= max_chars) or force):
            continue
        if force and ch not in END_PUNCT:
            # 硬切不要断在拉丁词中间：回退到最近的空格
            i = buf.rstrip().rfind(" ")
            if hard_max - 12 <= i:
                keep, drop = buf[:i + 1], buf[i + 1:]
                keep_n = cur - len(_norm(drop))
                pieces.append((keep, buf_start, keep_n))
                buf, buf_start = drop, keep_n
                continue
        pieces.append((buf, buf_start, cur))
        buf, buf_start = "", cur
    if buf.strip():
        pieces.append((buf, buf_start, cur))
    return pieces


def build_cues(text, words, max_chars=MAX_CUE_CHARS):
    """由已知文案 + edge-tts 字级边界生成字幕条。

    WordBoundary 的词文本不含标点，所以不能直接在词上断句。但词的规范化
    拼接与原文规范化完全一致，于是先按标点切原文，再把每片的字符区间映射
    回词的时间戳。

    text:  完整口播文案（含标点）
    words: [{"start": float, "end": float, "word": str}, ...]
    返回:  [{"start": float, "end": float, "text": str}, ...]
    """
    norm_full = _norm(text)

    spans, pos = [], 0
    for w in words:
        nw = _norm(w.get("word") or "")
        if not nw:
            continue
        spans.append((pos, pos + len(nw), w))
        pos += len(nw)

    if pos != len(norm_full) or not spans:
        # 字符区间对不上就按词硬切，至少字幕文字是对的
        return _fallback_cues(words, max_chars)

    cues = []
    for ptext, a, b in _split_pieces(text, max_chars, HARD_MAX_CHARS):
        st = en = None
        for wa, wb, w in spans:
            if wb <= a:
                continue
            if wa >= b:
                break
            if st is None:
                st = w["start"]
            en = w["end"]
        if st is None:
            continue
        t = _clean(ptext)
        if t:
            cues.append({"start": round(st, 3),
                         "end": round(max(en, st + 0.4), 3), "text": t})

    # 过短的字幕条与后一条合并，避免一闪而过
    merged = []
    for c in cues:
        if (merged and c["end"] - c["start"] < MIN_CUE_DUR
                and len(merged[-1]["text"]) + len(c["text"]) <= HARD_MAX_CHARS):
            merged[-1]["end"] = c["end"]
            merged[-1]["text"] = _clean(merged[-1]["text"] + c["text"])
        else:
            merged.append(dict(c))

    # 保证单调不重叠，且不超过最长展示时间
    for i, c in enumerate(merged):
        c["start"] = round(max(c["start"], merged[i - 1]["end"] if i else 0.0), 3)
        if c["end"] <= c["start"]:
            c["end"] = round(c["start"] + 0.5, 3)
        c["end"] = round(min(c["end"], c["start"] + MAX_CUE_DUR), 3)
    return merged


def _fallback_cues(words, max_chars):
    """字符区间对不上时的兜底：按词累计长度硬切"""
    cues, buf = [], []

    def flush():
        if not buf:
            return
        t = _clean("".join(w["word"] for w in buf))
        if t:
            cues.append({"start": round(buf[0]["start"], 3),
                         "end": round(buf[-1]["end"], 3), "text": t})
        buf.clear()

    n = 0
    for w in words:
        tok = (w.get("word") or "").strip()
        if not tok:
            continue
        buf.append(w)
        n += len(_norm(tok))
        if n >= max_chars:
            flush()
            n = 0
    flush()
    return cues


def apply_timings(content, speech_start, speech_end, cues, tail=TAIL):
    """用真实语音起止点重写 content.json 的时间轴。

    配音从封面内就开始（钩子），所以语音横跨 封面 → 概览 → 详情 三段，
    不是只落在详情段里。时间轴和字幕共用同一个 audio_offset——
    字幕偏移量和音轨铺入位置必须同源，否则会差一个固定偏移（音画不同步）。
    """
    detail_start = COVER_DUR + OVERVIEW_DUR
    audio_offset = AUDIO_OFFSET
    speech_abs_end = audio_offset + speech_end
    detail_end = speech_abs_end + tail

    list_start = detail_end
    n_pages = len(content.get("lists") or [])
    list_dur = 5.0 * max(1, n_pages)
    total = list_start + list_dur if n_pages else detail_end

    tl = content["timeline"]
    tl["cover"] = {"start": 0.0, "end": COVER_DUR}
    tl["overview"] = {"start": COVER_DUR, "end": detail_start}
    tl["detail"] = {"start": detail_start, "end": round(detail_end, 3)}
    tl["list_start"] = round(list_start, 3)
    tl["list_page_dur"] = 5.0
    tl["total_duration"] = round(total, 2)
    tl["audio_offset"] = audio_offset
    tl["speech"] = {"start": round(speech_start, 3), "end": round(speech_end, 3)}

    shift = audio_offset - speech_start
    kept = []
    for c in cues:
        s, e = c["start"] + shift, c["end"] + shift
        if e <= 0.0 or s >= detail_end:
            continue
        kept.append({"start": round(max(s, 0.0), 3),
                     "end": round(min(e, detail_end), 3),
                     "text": c["text"]})
    content["detail"]["cues"] = kept
    return content


def main():
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        print(__doc__)
        return 0
    data = json.loads(open(src, encoding="utf-8").read())
    print(json.dumps(data.get("timeline"), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    raise SystemExit(main())
