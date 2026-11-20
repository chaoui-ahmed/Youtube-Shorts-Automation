"""GTA_IVY: skip clips that show nudity (game strip clubs etc.). Uses NudeNet on sampled frames, offline."""
import logging
import os
import subprocess
import tempfile

EXPLICIT = {"FEMALE_BREAST_EXPOSED": 0.30, "FEMALE_GENITALIA_EXPOSED": 0.25, "MALE_GENITALIA_EXPOSED": 0.25,
            "ANUS_EXPOSED": 0.25, "BUTTOCKS_EXPOSED": 0.20}
_detector = None


def is_nsfw(video_path, samples=20):
    global _detector
    try:
        from nudenet import NudeDetector
        _detector = _detector or NudeDetector()
    except Exception as e:  # if the detector can't load, be safe and skip the clip
        logging.warning(f"[!] NudeNet unavailable ({e}), skipping clip to be safe")
        return True
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path],
                         capture_output=True, text=True).stdout.strip()
    dur = float(dur or 30)
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(samples):
            t = dur * (i + 0.5) / samples
            img = os.path.join(tmp, f"{i}.jpg")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", video_path,
                            "-frames:v", "1", "-vf", "scale=640:-2", img])
            if not os.path.exists(img):
                continue
            for d in _detector.detect(img):
                if d["score"] >= EXPLICIT.get(d["class"], 2):
                    logging.info(f"[-] Nudity detected ({d['class']} {d['score']:.2f} at {t:.0f}s), skipping clip")
                    return True
    return False
