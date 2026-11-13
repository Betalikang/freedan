#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段5：出片

content.json 的时间轴已由 04_narrate 按真实音频定好，本阶段只负责：
  1. 按 cues 切分时间片段（字幕写进 .cap）
  2. 渲染画面 → 拼接
  3. 把 narration.wav 原样铺到详情段起点（不做变速）

产出：
  runs/<date>/video.mp4
"""

import sys
import json
import shutil
import subprocess
import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
REDESIGN = Path(CFG["paths"]["redesign"])
SR = 44100

sys.path.insert(0, str(REDESIGN / "scripts"))
from render_video import build_segments, write_seg_html  # noqa: E402
from render_slides import render  # noqa: E402


def probe_duration(path):
    o = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(o.stdout.strip())
    except ValueError:
        return 0.0


def build_track(narration, audio_offset, total, out_wav):
    """整段配音一次铺到 audio_offset 处；语速已由 TTS 决定，不做任何拉伸。

    audio_offset 必须与 timeline.py 里 apply_timings 用的同一个值，
    否则字幕会与语音差一个固定偏移。
    """
    import numpy as np
    import soundfile as sf

    data, fs = sf.read(str(narration), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if fs != SR:
        idx = np.linspace(0, len(data) - 1, int(len(data) * SR / fs))
        data = np.interp(idx, np.arange(len(data)), data).astype(np.float32)

    n = int(total * SR) + SR
    track = np.zeros(n, dtype=np.float32)
    a = int(audio_offset * SR)
    b = min(a + len(data), n)
    track[a:b] += data[: b - a]

    peak = float(np.max(np.abs(track))) or 1.0
    track = track / peak * 0.89
    sf.write(str(out_wav), track, SR)
    return out_wav


def ensure_bgm():
    """BGM 文件不存在时，从源视频里抽一段纯音乐（原片解说结束后的部分）"""
    b = CFG["video"].get("bgm") or {}
    if not b:
        return None
    p = ROOT / b.get("file", "assets/bgm.wav")
    if p.exists():
        return p
    src = b.get("source_video")
    if not src or not Path(src).exists():
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-ss", str(b.get("source_start", 101.4)),
         "-to", str(b.get("source_end", 146.0)),
         "-i", src, "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(p)],
        capture_output=True, text=True)
    return p if r.returncode == 0 and p.exists() else None


def mix_bgm(track, total, out_wav):
    """给配音轨铺背景音乐。

    BGM 用 acrossfade 自环到成片长度，避免循环接缝爆音；
    人声作为侧链触发 sidechaincompress，说话时自动压低 BGM、停口时回升；
    末尾统一限幅，防止人声与 BGM 叠加削波。
    """
    b = CFG["video"].get("bgm") or {}
    src = ensure_bgm()
    if not src:
        print("  ⚠ 无 BGM 可用，只出人声")
        shutil.copyfile(track, out_wav)
        return out_wav

    d = b.get("duck") or {}
    fade_in = b.get("fade_in", 0.8)
    fade_out = b.get("fade_out", 2.5)
    hp = b.get("highpass_hz", 110)
    fc = (
        f"[1]asplit=2[a][b2];"
        f"[a][b2]acrossfade=d={b.get('crossfade', 2.0)}:c1=tri:c2=tri,"
        f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
        f"highpass=f={hp},"
        f"afade=t=in:d={fade_in},"
        f"afade=t=out:st={max(0.0, total - fade_out):.3f}:d={fade_out},"
        f"volume={b.get('volume_db', -6)}dB[bgm];"
        f"[bgm][0]sidechaincompress="
        f"threshold={d.get('threshold', 0.03)}:ratio={d.get('ratio', 10)}"
        f":attack={d.get('attack', 25)}:release={d.get('release', 400)}:makeup=1[duck];"
        f"[0][duck]amix=inputs=2:duration=first:normalize=0,"
        f"alimiter=limit=0.95:level=false[mix]"
    )
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(track), "-i", str(src),
         "-filter_complex", fc, "-map", "[mix]",
         "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(out_wav)],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠ BGM 混音失败，退回纯人声\n{r.stderr[-500:]}")
        shutil.copyfile(track, out_wav)
    return out_wav


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    run_dir = ROOT / "runs" / date
    content_path = run_dir / "content.json"
    if not content_path.exists():
        print(f"✗ 缺少 {content_path}")
        return 1

    data = json.loads(content_path.read_text(encoding="utf-8"))
    tl = data["timeline"]
    total = tl["total_duration"]
    cues = data["detail"].get("cues") or []
    print(f"出片 {date}  时长 {total}s  字幕 {len(cues)} 条")

    # 1) 音轨
    narration = run_dir / "narration.wav"
    if not narration.exists():
        print(f"✗ 缺少 {narration}（先跑 04_narrate.py）")
        return 1
    track = run_dir / "_track.wav"
    audio_offset = tl.get("audio_offset", 0.5)
    build_track(narration, audio_offset, total, track)

    # 1b) 铺背景音乐（人声侧链闪避）
    mixed = run_dir / "_mix.wav"
    mix_bgm(track, total, mixed)

    # 2) 画面
    print("  2/4 渲染画面...")
    work = run_dir / "_render"
    seg_dir = work / "segments"
    png_dir = work / "frames"
    shutil.rmtree(work, ignore_errors=True)
    seg_dir.mkdir(parents=True)
    png_dir.mkdir(parents=True)
    shutil.copy(REDESIGN / "html" / "base.css", seg_dir / "base.css")

    segs = build_segments(data)
    htmls = [write_seg_html(data, s, seg_dir, i) for i, s in enumerate(segs)]
    render(htmls, png_dir)
    print(f"    {len(segs)} 个片段")

    # 3) 拼接
    print("  3/4 拼接视频...")
    concat = work / "concat.txt"
    lines = []
    for i, seg in enumerate(segs):
        png = png_dir / f"seg_{i:03d}_{seg['kind']}.png"
        lines.append(f"file '{png.as_posix()}'")
        lines.append(f"duration {seg['end'] - seg['start']:.3f}")
    last = segs[-1]
    lines.append(f"file '{(png_dir / f'seg_{len(segs)-1:03d}_{last['kind']}.png').as_posix()}'")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")

    silent = work / "silent.mp4"
    r = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-fps_mode", "cfr", "-pix_fmt", "yuv420p", "-c:v", "libx264",
        "-crf", "20", "-preset", "medium", "-r", str(CFG["video"]["fps"]),
        str(silent)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1200:])
        return 1

    # 4) 合音
    print("  4/4 合入配音与背景音乐...")
    out = run_dir / "video.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(silent), "-i", str(mixed),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest",
                        "-movflags", "+faststart", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1000:])
        return 1
    actual = probe_duration(out)
    if abs(actual - total) > 0.5:
        fixed = work / "fixed.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(out), "-t", f"{total:.2f}",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", str(fixed)],
                       capture_output=True)
        shutil.move(str(fixed), str(out))

    print(f"\n✓ 成片: {out} ({probe_duration(out):.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
