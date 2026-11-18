#!/usr/bin/env python3
"""
GTA_IVY: post each new YouTube Short on X with its YouTube link, so X shows the video card.

Reads the channel's public RSS feed (no YouTube API / no Google project needed), skips videos
already tweeted (data/channels/GTAIVY/tweeted_youtube.txt) and posts the rest via Buffer.

Env: BUFFER_API_KEY, YOUTUBE_CHANNEL_ID (UC...), optional MAX_TWEETS (default 2)
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from post_to_buffer import channels, gql, MUTATION, KEY

CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
MAX_TWEETS = int(os.getenv("MAX_TWEETS", "2"))
STATE = os.path.join("data", "channels", "GTAIVY", "tweeted_youtube.txt")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}


def feed():
    r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}", timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    for e in root.findall("a:entry", NS):
        yield {
            "id": e.findtext("yt:videoId", "", NS),
            "title": e.findtext("a:title", "", NS),
            "published": datetime.fromisoformat(e.findtext("a:published", "", NS).replace("Z", "+00:00")),
            "description": e.findtext("media:group/media:description", "", NS) or "",
        }


def tweet_text(v):
    title = re.sub(r"\s*\|\s*GTA 6\s*#shorts\s*$", "", v["title"], flags=re.IGNORECASE).strip()
    credit = re.search(r"twitch\.tv/(\w+)", v["description"])
    lines = [title, ""]
    if credit:
        lines.append(f"🎥 twitch.tv/{credit.group(1)}")
    lines += ["#GTA6", "", f"https://youtube.com/shorts/{v['id']}"]
    return "\n".join(lines)


def main():
    if not (KEY and CHANNEL_ID):
        print("BUFFER_API_KEY or YOUTUBE_CHANNEL_ID missing: skipping X posts.")
        return
    x = [c for c in channels() if c["service"] == "twitter"]
    if not x:
        sys.exit("No X/Twitter channel in Buffer")
    done = set(open(STATE).read().split()) if os.path.exists(STATE) else set()
    recent = datetime.now(timezone.utc) - timedelta(hours=48)
    new = [v for v in feed() if v["id"] and v["id"] not in done and v["published"] >= recent]
    new.sort(key=lambda v: v["published"])
    posted = 0
    for v in new[:MAX_TWEETS]:
        inp = {"text": tweet_text(v), "channelId": x[0]["id"], "schedulingType": "automatic", "mode": "shareNow"}
        res = gql(MUTATION, {"input": inp})["createPost"]
        if res.get("post"):
            posted += 1
            done.add(v["id"])
            print(f"[+] X post for {v['id']}: {v['title']}")
        else:
            print(f"[!] X post failed for {v['id']}: {res.get('message')}")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        f.write("\n".join(sorted(done)) + "\n")
    print(f"{posted} X post(s), {max(0, len(new) - posted)} left for next run")


if __name__ == "__main__":
    main()
