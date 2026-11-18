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


def _classify(norm):
    for name, group in (("laugh", LAUGH), ("wtf", WTF), ("win", WIN), ("loss", LOSS), ("hype", HYPE)):
        if norm in group or (norm.split() and norm.split()[0] in group and len(norm.split()) <= 2):
            return name
    return None


def _readable(raw_msg, norm):
    if not norm or BLOCK.search(norm):
        return False
    words = norm.split()
    if not (2 <= len(words) <= 7) or len(norm) > 40:
        return False
    if any(EMOTE_LIKE.match(w) for w in raw_msg.split()):
        return False
    letters = sum(c.isalpha() for c in norm)
    return letters >= 0.6 * len(norm.replace(" ", ""))


def title_from_messages(messages):
    """messages: list of raw chat strings. Returns a hook string or None."""
    phrases, classes = Counter(), Counter()
    for raw in messages:
        norm = _normalize(raw)
        if not norm:
            continue
        cls = _classify(norm)
        if cls:
            classes[cls] += 1
        elif _readable(raw, norm):
            phrases[norm] += 1
    if phrases:
        phrase, n = phrases.most_common(1)[0]
        if n >= 3:
            emoji = {"laugh": " 😂", "wtf": " 💀", "win": " 🏆", "loss": " 💀", "hype": " 🔥"}.get(
                classes.most_common(1)[0][0] if classes else "", "")
            return phrase + emoji
    if classes:
        cls, n = classes.most_common(1)[0]
        if n >= 5:
            return TEMPLATES[cls]
    return None


def fetch_clip_chat(vod_id, vod_offset, duration, max_messages=3000):
    """Chat messages sent during the clip (+8s for reactions). Empty list on any problem."""
    if not vod_id or vod_offset is None:
        return []
    try:
        from chat_downloader import ChatDownloader
        start = max(0, int(vod_offset))
        end = start + int(duration or 30) + 8
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
