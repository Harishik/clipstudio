"""Auto-reframe (the 'track' layout): a 9:16 window that follows whoever is talking, like top clip channels do.

Faces are found a few times per second; the active speaker is the face whose mouth area moves most.
Like a human editor, the frame HOLDS on a subject and hard-CUTS to the next one (no seasick panning).
"""
from __future__ import annotations

import subprocess

import numpy as np

from .util import ffprobe_duration, ffprobe_size


def plan(video, fps: float = 4.0, min_hold: float = 1.2) -> list[tuple[float, float, float]]:
    """Return holds [(start, end, center_x_in_source_px)]."""
    import cv2
    sw, sh = ffprobe_size(video)
    dur = ffprobe_duration(video)
    pw = 640
    ph = int(sh * pw / sw) // 2 * 2
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={pw}:{ph},format=gray",
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    fs = pw * ph
    prev = None
    targets = []  # per sample: center x (in preview px) or None
    while True:
        b = proc.stdout.read(fs)
        if len(b) < fs:
            break
        g = np.frombuffer(b, dtype=np.uint8).reshape(ph, pw)
        faces = casc.detectMultiScale(g, 1.1, 5, minSize=(pw // 16, pw // 16))
        best, best_s = None, -1.0
        for (x, y, w, h) in faces:
            mouth = (slice(y + int(h * 0.6), min(ph, y + int(h * 1.05))), slice(x + w // 5, x + w - w // 5))
            motion = float(np.mean(np.abs(g[mouth].astype(np.int16) - prev[mouth].astype(np.int16)))) \
                if prev is not None and g[mouth].size else 0.0
            s = motion * 2.0 + (w / pw) * 30
            if s > best_s:
                best, best_s = x + w / 2, s
        targets.append(best)
        prev = g
    proc.wait()
    if not targets:
        return [(0.0, dur, sw / 2)]
    # fill gaps with last known
    last = pw / 2
    filled = []
    for t in targets:
        last = t if t is not None else last
        filled.append(last)
    # hysteresis: switch only when a new position persists for min_hold
    step = 1.0 / fps
    holds, cur_x, cur_start = [], filled[0], 0.0
    cand, cand_start = None, None
    for i, x in enumerate(filled):
        t = i * step
        if abs(x - cur_x) > pw * 0.12:
            if cand is None or abs(x - cand) > pw * 0.12:
                cand, cand_start = x, t
            elif t - cand_start >= min_hold:
                holds.append((cur_start, cand_start, cur_x))
                cur_x, cur_start, cand = cand, cand_start, None
        else:
            cand = None
            cur_x = cur_x * 0.9 + x * 0.1  # tiny drift toward the subject inside a hold
    holds.append((cur_start, dur, cur_x))
    k = sw / pw
    return [(round(a, 2), round(b, 2), x * k) for a, b, x in holds if b - a > 0.05]


def crop_expr(holds, sw: int, sh: int) -> tuple[int, str]:
    cw = int(sh * 9 / 16) // 2 * 2
    parts = []
    for a, b, cx in holds:
        x = int(min(max(cx - cw / 2, 0), sw - cw))
        parts.append(f"{x}*gte(t,{a})*lt(t,{b})")
    return cw, "+".join(parts) if parts else str((sw - cw) // 2)
