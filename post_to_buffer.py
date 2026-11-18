#!/usr/bin/env python3
"""
GTA_IVY: queue every Short from out/ on YouTube + TikTok through Buffer's API.

Buffer is a verified YouTube client, so Shorts are public (direct API uploads from an
unaudited Google project are locked to private).

Env:
  BUFFER_API_KEY   personal key from Buffer (GitHub secret)
  RELEASE_TAG      tag of the GitHub Release holding the .mp4 files
  GITHUB_REPOSITORY  owner/repo (set by GitHub Actions)
  BUFFER_SERVICES  optional, default "youtube,tiktok"
"""
import glob, json, os, sys
import requests

API = "https://api.buffer.com"
KEY = os.getenv("BUFFER_API_KEY", "").strip()
TAG = os.getenv("RELEASE_TAG", "").strip()
REPO = os.getenv("GITHUB_REPOSITORY", "").strip()
SERVICES = [s.strip() for s in os.getenv("BUFFER_SERVICES", "youtube,tiktok,twitter").split(",") if s.strip()]
ONLY_FILE = os.getenv("ONLY_FILE", "").strip()  # optional: post just this .mp4 name

MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}"""


def gql(query, variables=None):
    r = requests.post(API, json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {KEY}"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"])[:500])
    return data["data"]


def channels():
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    out = []
    for o in orgs:
        q = "query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id name service } }"
        out += gql(q, {"o": o["id"]})["channels"]
    return out


def create(channel, text, video_url, title):
    base = {
        "text": text,
        "channelId": channel["id"],
        "schedulingType": "automatic",
        # fresh Short goes to the NEXT slot, ahead of any older backlog
        "mode": os.getenv("QUEUE_MODE", "shareNext"),
        "assets": [{"video": {"url": video_url}}],
    }
    tries = []
    if channel["service"] == "twitter":
        base = {**base, "mode": os.getenv("X_MODE", "shareNow")}
    if channel["service"] == "youtube":
        tries.append({**base, "metadata": {"youtube": {"title": title[:100], "privacy": "public", "categoryId": "20"}}})
        tries.append({**base, "metadata": {"youtube": {"title": title[:100]}}})
    elif channel["service"] == "tiktok":
        tries.append({**base, "metadata": {"tiktok": {"title": title[:90]}}})
    tries.append(base)
    tries.append({**base, "mode": "addToQueue"})  # fallback if shareNext isn't accepted
    last = None
    for inp in tries:
        try:
            res = gql(MUTATION, {"input": inp})["createPost"]
        except RuntimeError as e:  # schema mismatch on metadata -> try simpler input
            last = str(e)
            continue
        if res.get("post"):
            return res["post"]["id"]
        last = res.get("message")
    raise RuntimeError(last)


def main():
    if not KEY:
        print("BUFFER_API_KEY not set: skipping Buffer posting (Shorts are still in the GitHub Release).")
        return
    if not (TAG and REPO):
        sys.exit("RELEASE_TAG / GITHUB_REPOSITORY missing")
    targets = [c for c in channels() if c["service"] in SERVICES]
    print("Buffer channels:", ", ".join(f"{c['service']}:{c['name']}" for c in targets) or "none")
    failures = 0
    for meta_path in sorted(glob.glob("out/*.json")):
        meta = json.load(open(meta_path, encoding="utf-8"))
        name = os.path.basename(meta_path)[:-5] + ".mp4"
        url = f"https://github.com/{REPO}/releases/download/{TAG}/{name}"
        if ONLY_FILE and name != ONLY_FILE:
            continue
        if name in os.getenv("SKIP_FILES", "").split():
            continue
        title = meta.get("title") or "GTA 6 #shorts"
        text = f"{title}\n\n{meta.get('description', '')}".strip()
        hook = title.replace(" | GTA 6 #shorts", "").strip()
        streamer = meta.get("streamer") or ""
        x_text = "\n".join([hook, ""] + ([f"🎥 twitch.tv/{streamer}"] if streamer else []) +
                           ["#GTA6", "", "More GTA 6 clips: youtube.com/@GTA-ivy"])
        for c in targets:
            try:
                pid = create(c, x_text if c["service"] == "twitter" else text, url, title)
                print(f"[+] queued {name} on {c['service']} ({pid})")
            except Exception as e:
                failures += 1
                print(f"[!] {name} on {c['service']}: {e}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
