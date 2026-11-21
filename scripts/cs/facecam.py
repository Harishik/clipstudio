"""Find the streamer's webcam overlay automatically.

A webcam overlay is a face that stays in the SAME spot across frames (in-game faces move).
We sample frames, detect faces, keep the location that repeats, then grow it into a cam box.
The agent can always override with --facecam x,y,w,h after looking at a frame.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .util import ffprobe_duration, ffprobe_size


def _sample(video: Path, n: int = 8) -> list[Path]:
    dur = ffprobe_duration(video)
    d = Path(tempfile.mkdtemp())
    out = []
    for k in range(n):
        t = dur * (k + 0.5) / n
        p = d / f"{k}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-q:v", "3", str(p)], check=False)
        if p.exists():
            out.append(p)
    return out


def detect(video: Path) -> dict | None:
    try:
        import cv2
    except ImportError:
        return None
    W, H = ffprobe_size(video)
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    hits = []
    frames = _sample(video, 10)
    for p in frames:
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        faces = casc.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6, minSize=(max(24, W // 60),) * 2)
        for (x, y, w, h) in faces:
            hits.append((x + w / 2, y + h / 2, w, h))
    if not hits:
        return None
    # cluster by center within 6% of width
    best, best_n = None, 0
    for c in hits:
        grp = [h for h in hits if abs(h[0] - c[0]) < W * 0.06 and abs(h[1] - c[1]) < H * 0.06]
        if len(grp) > best_n:
            best_n, best = len(grp), grp
    if best_n < max(2, len(frames) // 3):
        return None  # face not stable -> probably in-game, not a webcam
    cx = sum(h[0] for h in best) / best_n
    cy = sum(h[1] for h in best) / best_n
    fw = sum(h[2] for h in best) / best_n
    if fw > W * 0.28:
        return {"fullcam": True}  # face fills the frame: just-chatting / IRL, no gameplay to split
    box = _snap_to_border(frames, cx, cy, fw, W, H)
    if box:
        x, y, w, h = box
        return {"x": x, "y": y, "w": w // 2 * 2, "h": h // 2 * 2, "frames_with_face": best_n,
                "frames": len(frames), "method": "border", "face_cx": int(cx), "face_cy": int(cy), "face_w": int(fw)}
    aspect = 1080 / 740  # matches the top panel, so nothing important is cropped away
    bw = min(W * 0.45, fw * 3.4)
    bh = bw / aspect
    if bh < fw * 2.2:  # keep head + shoulders
        bh = fw * 2.2
        bw = bh * aspect
    x = int(min(max(cx - bw / 2, 0), W - bw))
    y = int(min(max(cy - bh * 0.42, 0), H - bh))
    return {"x": x, "y": y, "w": int(bw) // 2 * 2, "h": int(bh) // 2 * 2, "frames_with_face": best_n,
            "frames": len(frames), "method": "estimate", "face_cx": int(cx), "face_cy": int(cy), "face_w": int(fw)}


def _snap_to_border(frames, cx, cy, fw, W, H):
    """The webcam overlay's border is an edge that never moves while gameplay changes around it.
    Find persistent straight edges around the face and use them as the crop box."""
    import cv2
    import numpy as np
    edges = []
    for p in frames:
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if g is not None and g.shape[1] == W:
            edges.append(cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), 15, 45) > 0)
    if len(edges) < 4:
        return None
    pers = np.sum(edges, axis=0) >= max(3, int(0.75 * len(edges)))
    r0, r1 = int(max(cy - 1.0 * fw, 0)), int(min(cy + 1.0 * fw, H))
    c0, c1 = int(max(cx - 1.0 * fw, 0)), int(min(cx + 1.0 * fw, W))

    def col_score(x):
        return pers[r0:r1, max(x - 1, 0):x + 2].any(axis=1).mean()

    def row_score(y):
        return pers[max(y - 1, 0):y + 2, c0:c1].any(axis=0).mean()

    def best(cands, fn, edge_val):
        sc = [(fn(v), v) for v in cands]
        good = [(s, v) for s, v in sc if s > 0.4]
        if good:  # the overlay border is the strongest continuous line; ties -> nearest to the face
            top_s = max(g[0] for g in good)
            return next(v for s_, v in good if s_ >= top_s - 0.08), True
        return edge_val, False

    left, okl = best(range(int(cx - 0.8 * fw), int(max(cx - 4.5 * fw, 1)), -1), col_score, 0)
    right, okr = best(range(int(cx + 0.8 * fw), int(min(cx + 4.5 * fw, W - 2))), col_score, W)
    top, okt = best(range(int(cy - 0.9 * fw), int(max(cy - 3.5 * fw, 1)), -1), row_score, 0)
    bottom, okb = best(range(int(cy + 0.9 * fw), int(min(cy + 3.5 * fw, H - 2))), row_score, H)
    found = sum([okl, okr, okt, okb])
    # an overlay touching the frame edge has that side on the frame border
    okl = okl or cx - 4.5 * fw <= 0
    okr = okr or cx + 4.5 * fw >= W
    okt = okt or cy - 3.5 * fw <= 0
    okb = okb or cy + 3.5 * fw >= H
    if found < 2 or not (okl and okr and okt and okb):
        return None
    inset = 3
    x, y = left + inset, top + inset
    w, h = right - left - 2 * inset, bottom - top - 2 * inset
    if w < 1.6 * fw or h < 1.6 * fw or w > W * 0.6 or h > H * 0.7:
        return None
    return int(x), int(y), int(w), int(h)
