"""
GTA_IVY: build a Short title from what Twitch chat spammed during the clip. No AI.

Rules (first match wins):
  1. a readable phrase spammed by >= 3 messages  -> "NO WAY HE DID THAT 💀"
  2. dominant reaction emote class               -> templated hook
  3. nothing usable                              -> None (caller falls back to the clip title)
"""
import logging
import re
from collections import Counter

LAUGH = {"KEKW", "LUL", "LULW", "OMEGALUL", "ICANT", "LMAO", "LMFAO", "LOL", "XD", "KEKL", "PEPELAUGH",
         "😂", "🤣", "💀", "SKULL", "DEADGE", "HAHA", "HAHAHA"}
HYPE = {"POG", "POGGERS", "POGCHAMP", "POGU", "PAGMAN", "LETSGO", "LETS GO", "🔥", "HYPE", "GIGACHAD", "CLAP", "EZ"}
WIN = {"W", "WW", "WWW", "DUB", "HUGE W"}
LOSS = {"L", "LL", "LLL", "RIP", "F", "SADGE", "PEPEHANDS", "BIBLETHUMP"}
WTF = {"?", "??", "???", "WHAT", "WTF", "HUH", "BRO WHAT", "MONKAS", "MONKAW", "NOWAY", "NO WAY", "AINTNOWAY", "😳", "😭"}

TEMPLATES = {
    "laugh": "Chat lost it 😂",
    "hype": "This is insane 🔥",
    "win": "Massive W 🏆",
    "loss": "Biggest L ever 💀",
    "wtf": "What just happened?! 😳",
}

# Never put these in a title.
BLOCK = re.compile(r"n[i1]gg|f[a@]gg?ot|retard|tranny|kys|kill yourself|cunt|whore|slut|nazi|hitler|rape",
                   re.IGNORECASE)
EMOTE_LIKE = re.compile(r"^[A-Z][a-z]+[A-Z]\w*$")  # CamelCase emotes like monkaS, PepeHands


def _normalize(msg):
    msg = re.sub(r"https?://\S+|@\w+", "", msg).strip()
    words = msg.split()
    if not words:
        return ""
    # "KEKW KEKW KEKW" -> "KEKW", "W W W" -> "W"
    dedup = []
    for w in words:
        if not dedup or w.upper() != dedup[-1].upper():
            dedup.append(w)
    return " ".join(dedup).upper()[:60]


LAUGH_RE = re.compile(r"^(K{3,}|(HA|AH|JA|HE|HI|XA)+H?|RS(RS)+|5{3,}|(WK)+W?|LO+L|LMF?A+O+|XD+)$")


def _classify(norm):
    if LAUGH_RE.match(norm.replace(" ", "")):
        return "laugh"
    for name, group in (("laugh", LAUGH), ("wtf", WTF), ("win", WIN), ("loss", LOSS), ("hype", HYPE)):
        if norm in group or (norm.split() and norm.split()[0] in group and len(norm.split()) <= 2):
            return name
    return None


def _readable(raw_msg, norm):
    if not norm or BLOCK.search(norm):
        return False
    words = norm.split()
    if not (1 <= len(words) <= 7) or len(norm) > 40 or (len(words) == 1 and len(norm) < 4):
        return False
    if any(EMOTE_LIKE.match(w) for w in raw_msg.split()):
        return False
    if len(set(norm.replace(" ", ""))) < 3 or not _latin_ok(norm):
        return False
    letters = sum(c.isalpha() for c in norm)
    return letters >= 0.6 * len(norm.replace(" ", ""))


def _key(norm):
    # "KILL THE TIGERRS" / "Kill the tiger" / "KNIFEEE" -> same bucket
    k = re.sub(r"(.)\1+", r"\1", norm)
    return re.sub(r"S\b", "", k)


def title_from_messages(messages):
    """messages: list of raw chat strings. Returns a hook string or None."""
    buckets, display, classes = Counter(), {}, Counter()
    total = 0
    for raw in messages:
        norm = _normalize(raw)
        if not norm:
            continue
        total += 1
        cls = _classify(norm)
        if cls:
            classes[cls] += 1
        elif _readable(raw, norm):
            k = _key(norm)
            buckets[k] += 1
            display.setdefault(k, Counter())[norm] += 1
    need = max(2, int(0.05 * total))
    for k, n in buckets.most_common():
        words = k.split()
        if n >= need and (len(words) >= 2 or n >= need + 2):
            phrase = display[k].most_common(1)[0][0]
            phrase = re.sub(r"(.)\1{2,}", r"\1\1", phrase)  # KNIFEEEEE -> KNIFEE
            top_cls = classes.most_common(1)[0][0] if classes else ""
            emoji = {"laugh": " 😂", "wtf": " 💀", "win": " 🏆", "loss": " 💀", "hype": " 🔥"}.get(top_cls, "")
            return phrase + emoji
    if classes:
        cls, n = classes.most_common(1)[0]
        if n >= max(3, int(0.1 * total)):
            return TEMPLATES[cls]
    return None


GQL = "https://gql.twitch.tv/gql"
GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch web player's public client id
COMMENTS_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


def _gql_comments(vod_id, start, end, max_pages=15):
    import requests
    out, cursor = [], None
    for _ in range(max_pages):
        variables = {"videoID": str(vod_id)}
        if cursor:
            variables["cursor"] = cursor
        else:
            variables["contentOffsetSeconds"] = start
        body = [{"operationName": "VideoCommentsByOffsetOrCursor", "variables": variables,
                 "extensions": {"persistedQuery": {"version": 1, "sha256Hash": COMMENTS_HASH}}}]
        r = requests.post(GQL, json=body, headers={"Client-Id": GQL_CLIENT_ID}, timeout=15)
        r.raise_for_status()
        comments = (((r.json()[0].get("data") or {}).get("video") or {}).get("comments")) or {}
        edges = comments.get("edges") or []
        if not edges:
            break
        for e in edges:
            node = e.get("node") or {}
            t = node.get("contentOffsetSeconds", 0)
            if t > end:
                return out
            if t >= start:
                frags = ((node.get("message") or {}).get("fragments")) or []
                out.append("".join(f.get("text", "") for f in frags))
        if not (comments.get("pageInfo") or {}).get("hasNextPage"):
            break
        cursor = edges[-1].get("cursor")
        if not cursor:
            break
    return out


def fetch_clip_chat(vod_id, vod_offset, duration, max_messages=3000):
    """Chat messages sent during the clip (+8s for reactions). Empty list on any problem."""
    if not vod_id or vod_offset is None:
        return []
    start = max(0, int(vod_offset))
    end = start + int(duration or 30) + 8
    try:
        msgs = _gql_comments(vod_id, start, end)
        if msgs:
            return msgs[:max_messages]
    except Exception as e:
        logging.warning(f"[-] Twitch GQL chat failed for VOD {vod_id}: {e}")
    try:
        from chat_downloader import ChatDownloader
        chat = ChatDownloader().get_chat(f"https://www.twitch.tv/videos/{vod_id}",
                                         start_time=start, end_time=end, max_messages=max_messages)
        return [m.get("message", "") for m in chat if m.get("message")]
    except Exception as e:
        logging.warning(f"[-] Chat replay unavailable for VOD {vod_id}: {e}")
        return []


def chat_hook(video):
    """video: candidate dict from twitch_finder. Returns (hook or None, n_messages)."""
    msgs = fetch_clip_chat(video.get("vod_id"), video.get("vod_offset"), video.get("duration"))
    return title_from_messages(msgs), len(msgs)


GENERIC = ["Only in GTA 6", "GTA 6 is wild", "Wait for it...", "GTA 6 never misses", "This is GTA 6"]


def _latin_ok(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) >= 0.9 * len(letters)


def pick_title(hook, clip_title):
    """Chat hook first, else the Twitch clip title if it's clean English-looking text, else a generic hook."""
    import random
    if hook:
        return hook
    t = re.sub(r"\s+", " ", (clip_title or "")).strip()
    if t and _latin_ok(t) and not BLOCK.search(t) and len(set(t.lower())) >= 4 and len(t) >= 6:
        return t
    return random.choice(GENERIC)
