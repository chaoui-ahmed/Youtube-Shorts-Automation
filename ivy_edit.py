"""
GTA_IVY editing: full 16:9 gameplay on a blurred 9:16 background, hook on top,
streamer credit under the video, normal speed, light colour boost.
"""
import os
import re
import subprocess
import textwrap

import config

FONT = os.path.join(config.FONTS_DIR, "ivy_poppins_bold.ttf")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")
MAX_SECONDS = 59


def _clean(text):
    return re.sub(r"\s+", " ", EMOJI.sub("", text or "")).strip()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # drawtext textfile paths: escape for the filter graph
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def render(src, out_path, hook, streamer, duration=None):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    work = os.path.splitext(out_path)[0]
    lines = textwrap.wrap(_clean(hook).upper(), width=16)[:3] or ["GTA 6"]
    files = [_write(f"{work}_hook{i}.txt", line) for i, line in enumerate(lines)]
    credit_file = _write(work + "_credit.txt", f"clip: twitch.tv/{streamer}" if streamer else "")
    font = FONT.replace("\\", "/").replace(":", r"\:")
    line_h = 100
    top = 566 - line_h * len(lines)  # sits just above the video
    hook_filters = "".join(
        f"drawtext=fontfile='{font}':textfile='{f}':fontsize=84:fontcolor=white:"
        f"borderw=7:bordercolor=black:x=(w-text_w)/2:y={top + i * line_h},"
        for i, f in enumerate(files)
    )

    t = min(float(duration or MAX_SECONDS), MAX_SECONDS)
    graph = (
        "[0:v]split=2[bgsrc][fgsrc];"
        "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=22:2,eq=brightness=-0.12:saturation=1.1[bg];"
        "[fgsrc]scale=1080:-2:flags=lanczos,eq=contrast=1.06:saturation=1.12,unsharp=5:5:0.6[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2-60,"
        + hook_filters +
        f"drawtext=fontfile='{font}':textfile='{credit_file}':fontsize=42:fontcolor=white:"
        "borderw=4:bordercolor=black:x=(w-text_w)/2:y=(h/2)-60+330,"
        "format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", src, "-t", f"{t:.2f}",
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-r", "30", "-movflags", "+faststart", out_path,
    ]
    subprocess.run(cmd, check=True)
    for f in [work + "_credit.txt"] + [f"{work}_hook{i}.txt" for i in range(len(lines))]:
        try:
            os.remove(f)
        except OSError:
            pass
    return out_path
