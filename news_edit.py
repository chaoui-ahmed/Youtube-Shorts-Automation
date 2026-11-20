"""
GTA_IVY TikTok "news" layout (the format big gaming-news pages use):
  top half    = gameplay, zoomed in
  bottom half = the streamer's facecam, zoomed in (found with face detection)
  middle      = white rounded headline box with bold black text that tells the story
  bottom      = small "clip: twitch.tv/<streamer>" credit
Falls back to full-frame gameplay on a blurred background when there is no facecam.
"""
import os
import subprocess
import textwrap
from collections import Counter

import cv2
from PIL import Image, ImageDraw, ImageFont

import config

FONT = os.path.join(config.FONTS_DIR, "ivy_poppins_bold.ttf")
W, H = 1080, 1920
HALF = H // 2


def _probe(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "default=nw=1", src],
                         capture_output=True, text=True).stdout
    vals = dict(l.split("=") for l in out.split() if "=" in l)
    return int(vals.get("width", 1920)), int(vals.get("height", 1080)), float(vals.get("duration", 30))


def find_facecam(src, samples=8):
    """Return (x, y, w, h) of the streamer's webcam area, or None."""
    xml = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "haarcascade_frontalface_default.xml")
    cascade = cv2.CascadeClassifier(xml)
    if cascade.empty():
        return None
    cap = cv2.VideoCapture(src)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300
    fw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920
    fh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080
    hits = []
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (i + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.15, 6, minSize=(int(fh * 0.05), int(fh * 0.05)))
        for (x, y, w, h) in faces:
            if h < fh * 0.35:  # webcam faces are small; a huge face is probably a game cutscene
                hits.append((x, y, w, h))
    cap.release()
    if len(hits) < 3:
        return None
    # keep the face position that shows up most often (the webcam doesn't move)
    grid = Counter((int(x / fw * 8), int(y / fh * 8)) for x, y, w, h in hits)
    cell, count = grid.most_common(1)[0]
    if count < 3:
        return None
    same = sorted([b for b in hits if (int(b[0] / fw * 8), int(b[1] / fh * 8)) == cell], key=lambda b: b[2])
    x, y, w, h = same[len(same) // 2]
    cx, cy = x + w / 2, y + h / 2
    bw = min(fw, w * 3.2)
    bh = min(fh, bw * HALF / W)  # same aspect as the bottom half (9:8)
    bx = max(0, min(fw - bw, cx - bw / 2))
    by = max(0, min(fh - bh, cy - bh * 0.42))
    return int(bx), int(by), int(bw) // 2 * 2, int(bh) // 2 * 2


def headline_png(text, path, width=960):
    font = ImageFont.truetype(FONT, 62)
    lines = textwrap.wrap(text, width=24)[:4]
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    line_h = 76
    text_w = max(draw.textlength(l, font=font) for l in lines)
    box_w = int(min(width, text_w + 70))
    box_h = int(len(lines) * line_h + 46)
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=22, fill=(255, 255, 255, 255))
    for i, l in enumerate(lines):
        lw = d.textlength(l, font=font)
        d.text(((box_w - lw) / 2, 18 + i * line_h), l, font=font, fill=(10, 10, 10, 255))
    img.save(path)
    return path, box_w, box_h


def render(src, out_path, headline, streamer, max_seconds=59):
    sw, sh, dur = _probe(src)
    t = min(dur, max_seconds)
    work = os.path.splitext(out_path)[0]
    png, bw, bh = headline_png(headline, work + "_headline.png")
    cam = find_facecam(src)
    credit = f"clip: twitch.tv/{streamer}" if streamer else ""
    font = FONT.replace(":", r"\:")
    credit_file = work + "_credit.txt"
    open(credit_file, "w").write(credit)
    if cam:
        cx, cy, cw, ch = cam
        graph = (
            # top: gameplay zoomed to fill 1080x960
            f"[0:v]scale=-2:{HALF}:flags=lanczos,crop={W}:{HALF},eq=contrast=1.05:saturation=1.1[top];"
            # bottom: facecam zoomed to fill 1080x960
            f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale={W}:{HALF}:flags=lanczos[bot];"
            "[top][bot]vstack[stack];"
        )
        box_y = HALF - bh // 2
    else:
        graph = (
            "[0:v]split=2[bgs][fgs];"
            f"[bgs]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=22:2[bg];"
            f"[fgs]scale={W}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[stack];"
        )
        box_y = int(H / 2 - (W * sh / sw) / 2 - bh - 30)
    graph += (
        f"[stack][1:v]overlay=(W-w)/2:{box_y},"
        f"drawtext=fontfile='{font}':textfile='{credit_file}':fontsize=38:fontcolor=white:"
        "borderw=4:bordercolor=black:x=(w-text_w)/2:y=h-260,format=yuv420p[v]"
    )
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-i", png, "-t", f"{t:.2f}",
                    "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_path], check=True)
    for f in (png, credit_file):
        try:
            os.remove(f)
        except OSError:
            pass
    return out_path, bool(cam)
