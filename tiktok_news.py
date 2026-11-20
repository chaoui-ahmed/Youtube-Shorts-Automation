#!/usr/bin/env python3
"""
GTA_IVY TikTok: one "news" clip per run. Most-viewed fresh GTA 6 clip from a big streamer,
split-screen (gameplay / facecam), headline box built from real Twitch data
(stream uptime, live viewers, clip views, what chat spammed).
"""
import json
import logging
import os
import re
from datetime import datetime, timezone

import requests

import config
from chat_title import chat_hook, fetch_clip_chat
from twitch_finder import _NSFW
from news_edit import render
from twitch_downloader import download_twitch_clip
from twitch_finder import find_big_streamer_clips, find_twitch_clips, get_twitch_access_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
STATE = os.path.join("data", "channels", "GTAIVY", "tiktok_news.txt")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")
GENERIC = {"CHAT LOST IT", "THIS IS INSANE", "MASSIVE W", "BIGGEST L EVER", "WHAT JUST HAPPENED?!"}


def live_info(login):
    try:
        token = get_twitch_access_token()
        r = requests.get("https://api.twitch.tv/helix/streams", params={"user_login": login}, timeout=10,
                         headers={"Client-ID": config.TWITCH_CLIENT_ID.strip(), "Authorization": f"Bearer {token}"})
        data = r.json().get("data", [])
        if not data:
            return None
        s = data[0]
        start = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
        return {"hours": (datetime.now(timezone.utc) - start).total_seconds() / 3600,
                "viewers": s.get("viewer_count", 0), "game": s.get("game_name", "")}
    except Exception as e:
        logging.warning(f"live info failed for {login}: {e}")
        return None


def headline(clip, hook):
    name = clip.get("broadcaster_name") or "This streamer"
    live = live_info(clip.get("broadcaster_name", "").lower())
    hook_clean = EMOJI.sub("", hook or "").strip()
    if live and live["game"] == "Grand Theft Auto VI" and live["hours"] >= 4:
        return f"{name} is {int(live['hours'])} HOURS into GTA 6 with {live['viewers']:,} people watching"
    if hook_clean and hook_clean.upper() not in GENERIC and len(hook_clean) <= 40:
        return f'{name}\'s chat after this GTA 6 moment: "{hook_clean.upper()}"'
    if (clip.get("view_count") or 0) >= 2000:
        return f"This {name} GTA 6 moment already has {clip['view_count']:,} views"
    if hook_clean.upper() == "CHAT LOST IT":
        return f"{name}'s chat could NOT handle this GTA 6 moment"
    return f"{name} was NOT ready for this in GTA 6"


def main():
    os.makedirs("out", exist_ok=True)
    done = set(open(STATE).read().split()) if os.path.exists(STATE) else set()
    cfg = json.load(open("channels.json"))[0]["source_configuration"]
    pool = find_big_streamer_clips(cfg.get("big_streamers") or []) or find_twitch_clips(["Grand Theft Auto VI"])
    pool = [c for c in pool if c["video_id"] not in done]
    for clip in pool[:15]:
        src = download_twitch_clip(clip)
        if not src or not os.path.exists(src):
            continue
        msgs = fetch_clip_chat(clip.get("vod_id"), clip.get("vod_offset"), clip.get("duration"))
        if sum(1 for m in msgs if _NSFW.search(m) or re.search(r"🍑|🥵|🤤|😩|thicc|mommy|cake", m, re.I)) >= 3:
            logging.info(f"Chat suggests adult content in {clip['video_id']}, skipping")
            continue
        hook, n = chat_hook(clip)
        text = headline(clip, hook)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        out = os.path.join("out", f"tiktok_news_{stamp}_{clip['video_id'][:20]}.mp4")
        path, has_cam = render(src, out, text, clip.get("broadcaster_name", ""))
        if not path:
            logging.info(f"No facecam in {clip['video_id']}, trying the next clip")
            continue
        logging.info(f"News clip: {out} | facecam={has_cam} | {text}")
        streamer = clip.get("broadcaster_name", "")
        meta = {
            "title": text,
            "description": f"🎥 twitch.tv/{streamer}\n\n#GTA6 #GTAVI #{streamer} #gaming #fyp",
            "tags": "GTA 6,GTA VI,gaming",
            "streamer": streamer,
            "clip_url": clip.get("url", ""),
            "clip_ids": [clip["video_id"]],
        }
        json.dump(meta, open(out[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        open(STATE, "a").write(clip["video_id"] + "\n")
        return
    raise SystemExit("No usable fresh clip")


if __name__ == "__main__":
    main()
