#!/usr/bin/env python3
"""
GTA_IVY TikTok format: "Top 5 GTA 6 moments today" compilation, > 1 minute, AI voiceover.

- picks the 5 most-viewed fresh GTA 6 clips (last 24h, big streamers first, NSFW filtered)
- each segment: full-frame gameplay on blurred 9:16 background, "#N" + chat hook on top,
  streamer credit under the video, AI voice announcing the moment (game audio ducked under it)
- concatenates into one vertical video (target 65-90 s) and writes out/<name>.mp4 + .json
"""
import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone

import config
from chat_title import chat_hook, pick_title
from ivy_edit import render as ivy_render
from twitch_downloader import download_twitch_clip
from twitch_finder import find_big_streamer_clips, find_twitch_clips

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
N_CLIPS = int(os.getenv("COMPILATION_CLIPS", "5"))
SEG_MAX = float(os.getenv("SEGMENT_SECONDS", "16"))
VOICE = os.getenv("TTS_VOICE", "en-US-AndrewNeural")
STATE = os.path.join("data", "channels", "GTAIVY", "tiktok_compiled.txt")
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def run(cmd):
    subprocess.run(cmd, check=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-ryan-high")
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/{spk}/{q}/{v}"


def _piper_model():
    import requests
    d = os.path.join("data", "piper_voices")
    os.makedirs(d, exist_ok=True)
    spk, q = PIPER_VOICE.split("-")[1], PIPER_VOICE.split("-")[2]
    model = os.path.join(d, PIPER_VOICE + ".onnx")
    for name in (PIPER_VOICE + ".onnx", PIPER_VOICE + ".onnx.json"):
        path = os.path.join(d, name)
        if not os.path.exists(path):
            r = requests.get(PIPER_BASE.format(spk=spk, q=q, v=name), timeout=180)
            r.raise_for_status()
            open(path, "wb").write(r.content)
    return model


def tts(text, path):
    """AI voice: Piper neural TTS (offline, free). Falls back to espeak-ng only if Piper fails."""
    wav = path.rsplit(".", 1)[0] + ".wav"
    try:
        model = _piper_model()
        subprocess.run(["python", "-m", "piper", "-m", model, "-f", wav, "--length-scale", "0.92"],
                       input=text, text=True, check=True, capture_output=True)
    except Exception as e:
        logging.warning(f"Piper failed ({e}), using espeak-ng")
        run(["espeak-ng", "-v", "en-us", "-s", "165", "-w", wav, text])
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, path])
    return path


def spoken(hook, streamer):
    h = EMOJI.sub("", hook or "").strip().rstrip("!?.").lower()
    generic = {"chat lost it", "this is insane", "massive w", "biggest l ever", "what just happened",
               "only in gta 6", "gta 6 is wild", "wait for it...", "gta 6 never misses", "this is gta 6"}
    if not h or h in generic:
        return f"{streamer} with this one." if streamer else "Watch this."
    return f"{streamer}: {h}." if streamer else f"{h}."


def pick_clips():
    seen = set(open(STATE).read().split()) if os.path.exists(STATE) else set()
    big = []
    try:
        cfg = json.load(open("channels.json"))[0]["source_configuration"]
        big = find_big_streamer_clips(cfg.get("big_streamers") or [])
    except Exception as e:
        logging.warning(f"big-streamer lookup failed: {e}")
    general = find_twitch_clips(target_games=["Grand Theft Auto VI"])
    pool, ids = [], set()
    for c in big[:3] + general + big[3:]:  # up to 3 big names, then the most-viewed of the category
        if c["video_id"] in ids or c["video_id"] in seen:
            continue
        ids.add(c["video_id"])
        pool.append(c)
    return pool


def build():
    os.makedirs("out", exist_ok=True)
    work = os.path.join(config.get_processed_dir(), "compilation")
    os.makedirs(work, exist_ok=True)
    pool = pick_clips()
    logging.info(f"{len(pool)} candidate clips")
    segments, used = [], []
    est = 0.0
    for c in pool:
        # at least N_CLIPS, and keep adding (max 7) until the video is safely over 1 minute
        if len(used) >= 7 or (len(used) >= N_CLIPS and est >= 66):
            break
        src = download_twitch_clip(c)
        if not src or not os.path.exists(src):
            continue
        d = duration(src)
        if d < 6:
            continue
        hook, _ = chat_hook(c)
        hook = pick_title(hook, c.get("title"))
        c["hook"] = hook
        used.append(c)
        est += min(SEG_MAX, d - 0.5)
    if len(used) < 3:
        raise SystemExit(f"Only {len(used)} usable fresh clips, skipping today's compilation.")

    total = len(used)
    for i, c in enumerate(used):
        rank = total - i  # count down: #5 ... #1
        streamer = c.get("broadcaster_name", "")
        src = download_twitch_clip(c)
        d = duration(src)
        seg_len = min(SEG_MAX, d - 0.5)
        start = max(0.0, d - 1.0 - seg_len)  # end of the clip is where the moment usually lands
        trimmed = os.path.join(work, f"trim_{i}.mp4")
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", src, "-t", f"{seg_len:.2f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", trimmed])
        framed = ivy_render(trimmed, os.path.join(work, f"framed_{i}.mp4"), f"#{rank} {streamer}".strip(), streamer,
                            duration=seg_len)
        intro = f"Top {WORDS.get(total, total)} GTA 6 moments today. " if i == 0 else ""
        voice = tts(f"{intro}Number {WORDS.get(rank, rank)}. {streamer}." if streamer else f"{intro}Number {WORDS.get(rank, rank)}.",
                    os.path.join(work, f"voice_{i}.mp3"))
        vd = duration(voice)
        seg = os.path.join(work, f"seg_{i}.mp4")
        # game audio ducked to 25% while the voice talks, voice on top
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", framed, "-i", voice, "-filter_complex",
             f"[0:a]volume='if(lt(t,{vd + 0.2:.2f}),0.25,1)':eval=frame[g];"
             "[1:a]adelay=150|150,volume=1.6[v];[g][v]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", seg])
        segments.append(seg)

    lst = os.path.join(work, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(s)}'\n" for s in segments)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out = os.path.join("out", f"tiktok_top{total}_{stamp}.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", out])
    length = duration(out)
    logging.info(f"Compilation: {out} ({length:.0f}s, {total} clips)")

    credits = " · ".join(f"#{total - i} twitch.tv/{c.get('broadcaster_name', '')}" for i, c in enumerate(used))
    meta = {
        "title": f"Top {total} GTA 6 moments today 🔥",
        "description": f"🎥 {credits}\n\n#GTA6 #GTAVI #ViceCity #gaming #fyp",
        "tags": "GTA 6,GTA VI,Vice City,gaming",
        "streamer": "",
        "clip_url": "",
        "duration": round(length, 1),
    }
    with open(out[:-4] + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "a") as f:
        f.writelines(c["video_id"] + "\n" for c in used)
    if length < 61:
        logging.warning("Compilation is under 61 s: not eligible for TikTok Creator Rewards.")


if __name__ == "__main__":
    build()
