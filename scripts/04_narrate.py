#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段4：配音 + 时间对齐

整段文案一次性合成，而不是逐句合成。

为什么：每句单独合成时，edge-tts 会为每个 utterance 重新起音、重新落调、
句末还给一个完整停顿。10 句拼起来就是 10 段独立录音的听感——一顿一顿，
即使语速完全统一也不像人话。整段合成让语调跨句连续流动。

时间轴由真实音频决定，不做任何变速拉伸：edge-tts 的 WordBoundary 事件直接
给出每个词的精确偏移，语音起止点和字幕条都从它来，不需要 Whisper 转写
（base 模型会把 "Higgsfield" 听成 "K-Sleep"，字幕就全错了）。

产出：
  narration.wav   整段配音（44.1kHz 单声道）
  timings.json    字级边界 + 语音起止点 + 字幕条
  content.json    时间轴被真实音频重写（含 detail.cues）
"""

import sys
import json
import shutil
import asyncio
import subprocess
import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "pipeline.json").read_text(encoding="utf-8"))
SR = 44100

sys.path.insert(0, str(ROOT / "scripts"))
import timeline as T  # noqa: E402


async def synth_full(text, out_mp3, voice, rate, pitch):
    """整段合成；同时收集 WordBoundary 字级时间戳"""
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                               boundary="WordBoundary")
    words = []
    with open(out_mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                t = (ch.get("text") or "").strip()
                if t:
                    words.append({
                        "start": round(ch["offset"] / 1e7, 3),
                        "end": round((ch["offset"] + ch["duration"]) / 1e7, 3),
                        "word": t,
                    })
    return words


def to_wav(src, dst):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)],
        capture_output=True, text=True)
    return r.returncode == 0 and dst.exists()


def proportional_words(text, duration):
    """拿不到字级边界时的兜底：按字数比例均分"""
    chars = [c for c in text if not c.isspace()]
    n = max(1, len(chars))
    out, t = [], 0.0
    for c in chars:
        d = duration / n
        out.append({"start": round(t, 3), "end": round(t + d, 3), "word": c})
        t += d
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    content_path = run_dir / "content.json"
    sentences_path = run_dir / "sentences.json"

    if not content_path.exists() or not sentences_path.exists():
        print(f"✗ 缺少 {content_path} 或 {sentences_path}")
        return 1

    sentences = json.loads(sentences_path.read_text(encoding="utf-8")).get("sentences", [])
    if not sentences:
        print("✗ 没有口播稿")
        return 1

    vcfg = CFG["video"]
    voice = vcfg.get("voice", "zh-CN-XiaoxiaoNeural")
    rate = vcfg.get("rate", "+5%")
    pitch = vcfg.get("pitch", "+0Hz")

    # 补全句末标点，保证整段合成时语调正确收束
    text = "".join(s if s.rstrip().endswith(("。", "！", "？", "!", "?")) else s + "。"
                   for s in sentences)
    print(f"配音 {date}  {len(sentences)} 句 / {len(text)} 字  声线 {voice}  语速 {rate}")

    work = run_dir / "_tts"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    mp3 = work / "full.mp3"
    try:
        words = asyncio.run(synth_full(text, mp3, voice, rate, pitch))
    except Exception as e:
        print(f"✗ 合成失败: {e}")
        return 1
    if not mp3.exists() or mp3.stat().st_size < 1000:
        print("✗ 合成结果为空")
        return 1

    wav = run_dir / "narration.wav"
    if not to_wav(mp3, wav):
        print("✗ 转 wav 失败")
        return 1
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(wav)],
        capture_output=True, text=True).stdout.strip()
    dur = float(dur)

    if words:
        s0, s1 = words[0]["start"], words[-1]["end"]
        print(f"  整段一次合成 {dur:.1f}s，字级边界 {len(words)} 个，"
              f"语音 {s0:.2f}-{s1:.2f}s")
    else:
        print(f"  ⚠ 未取到字级边界，按字数比例兜底（音频 {dur:.1f}s）")
        words = proportional_words(text, dur)
        s0, s1 = 0.0, dur

    cues = T.build_cues(text, words)

    content = json.loads(content_path.read_text(encoding="utf-8"))
    content = T.apply_timings(content, s0, s1, cues)
    content_path.write_text(json.dumps(content, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    (run_dir / "timings.json").write_text(json.dumps(
        {"voice": voice, "rate": rate, "duration": dur, "words": words,
         "speech": {"start": s0, "end": s1}, "cues": cues},
        ensure_ascii=False, indent=1), encoding="utf-8")

    tl = content["timeline"]
    print(f"  字幕 {len(cues)} 条")
    print(f"  时间轴：详情 {tl['detail']['start']:.1f}-{tl['detail']['end']:.1f}s，"
          f"总长 {tl['total_duration']}s")
    print("✓ 配音与对齐完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
