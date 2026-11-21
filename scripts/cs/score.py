"""Moment finder: score every second of a stream from cheap signals, then pick peaks.

Signals (each turned into a z-score against its own local baseline):
  loud   — audio loudness vs the ~2 minutes around it (screams, explosions, hype)
  chat   — messages/second vs the surrounding 5 minutes (chat explodes when something happens)
  hype   — hype words / emotes in chat (KEKW, POG, "clip it", 💀 ...)
  replay — YouTube "most replayed" heatmap, when the video has one
Loud + busy is NOT the same as good: the agent must look at each candidate before cutting.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from . import chat as chatmod
from .util import ffprobe_duration, log, read_json, write_json

SR = 8000


def loudness_series(audio: Path) -> np.ndarray:
    """dBFS per second, streamed (works on multi-hour audio with little memory)."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         stdout=subprocess.PIPE)
    out = []
    leftover = np.zeros(0, dtype=np.float32)
    while True:
        b = p.stdout.read(SR * 2 * 60)
        if not b:
            break
        x = np.concatenate([leftover, np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0])
        n = len(x) // SR
        if n:
            blk = x[: n * SR].reshape(n, SR)
            rms = np.sqrt(np.mean(blk ** 2, axis=1) + 1e-12)
            out.append(20 * np.log10(rms + 1e-9))
        leftover = x[n * SR:]
    p.wait()
    return np.concatenate(out) if out else np.zeros(0)


def rolling_z(x: np.ndarray, win: int) -> np.ndarray:
    if len(x) == 0:
        return x
    k = np.ones(win) / win
    pad = win // 2
    xp = np.pad(x, pad, mode="edge")
    mean = np.convolve(xp, k, mode="same")[pad:-pad or None][: len(x)]
    sq = np.convolve(xp ** 2, k, mode="same")[pad:-pad or None][: len(x)]
    std = np.sqrt(np.maximum(sq - mean ** 2, 1e-6))
    return (x - mean) / (std + 1e-3)


def smooth(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) == 0 or w <= 1:
        return x
    return np.convolve(x, np.ones(w) / w, mode="same")


def chat_series(rows: list[dict], n: int) -> tuple[np.ndarray, np.ndarray]:
    rate = np.zeros(n)
    hype = np.zeros(n)
    for r in rows:
        i = int(r["t"])
        if 0 <= i < n:
            rate[i] += 1
            hype[i] += chatmod.hype_score(r.get("text", ""))
    return rate, hype


def heatmap_series(heat: list[dict], n: int) -> np.ndarray:
    h = np.zeros(n)
    for seg in heat or []:
        a, b = int(seg.get("start_time", 0)), int(seg.get("end_time", 0))
        h[max(a, 0):min(b, n)] = seg.get("value", 0)
    return h


WEIGHTS = {"loud": 1.0, "chat": 1.3, "hype": 0.8, "replay": 1.2, "speech": 0.9, "comments": 1.5, "visual": 0.7}

TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?![\d:])")


def comment_series(job: Path, n: int, max_comments: int = 1000) -> np.ndarray:
    """Timestamps viewers write in comments ("4:32 LMAO") mark the moments people loved. No login needed."""
    from .util import run, ytdlp_base
    cache = job / "comments.json"
    data = read_json(cache)
    if data is None:
        j = read_json(job / "job.json")
        if j["platform"] != "youtube":
            return np.zeros(n)
        log("reading top comments for timestamps...")
        r = run(ytdlp_base() + ["--skip-download", "--write-comments", "--no-write-info-json", "-J",
                                "--extractor-args", f"youtube:comment_sort=top;max_comments={max_comments},all,50,5",
                                j["url"]], check=False)
        try:
            data = [{"text": c.get("text", ""), "likes": c.get("like_count") or 0}
                    for c in (json.loads(r.stdout).get("comments") or [])]
        except json.JSONDecodeError:
            data = []
        write_json(cache, data)
    x = np.zeros(n)
    for c in data:
        for h, m, s_ in TS_RE.findall(c["text"]):
            t = int(h or 0) * 3600 + int(m) * 60 + int(s_)
            if 0 <= t < n:
                w = 1 + np.log1p(c["likes"])
                x[t:min(n, t + 12)] += w  # people timestamp the START of the moment
    return x


def visual_series(job: Path, n: int) -> np.ndarray:
    """On-screen action per second: motion energy + hard cuts, from a tiny 144p stream (never saved)."""
    from . import fetch
    cache = job / "visual.npy"
    if cache.exists():
        v = np.load(cache)
        return np.pad(v, (0, max(0, n - len(v))))[:n]
    j = read_json(job / "job.json")
    log("measuring on-screen action (tiny 144p copy, deleted after)...")
    src = j["url"]
    tmpv = None
    if j["platform"] != "local":
        from .util import run, ytdlp_base
        tmpv = job / "visual_144p.mp4"
        r = run(ytdlp_base() + ["-f", "wv*[height>=90]/worstvideo/worst", "-o", str(tmpv), "--force-overwrites",
                                j["url"]], check=False)
        if r.returncode != 0 or not tmpv.exists():
            try:
                src, _ = fetch.stream_urls(j["url"], max_height=160)
            except SystemExit:
                return np.zeros(n)
            tmpv = None
        else:
            src = str(tmpv)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-an", "-vf", "fps=2,scale=64:36,format=gray",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    fs = 64 * 36
    prev, diffs = None, []
    while True:
        b = p.stdout.read(fs)
        if len(b) < fs:
            break
        f = np.frombuffer(b, dtype=np.uint8).astype(np.float32)
        diffs.append(0.0 if prev is None else float(np.mean(np.abs(f - prev))))
        prev = f
    p.wait()
    if tmpv:
        tmpv.unlink(missing_ok=True)
    d = np.array(diffs)
    sec = d[: len(d) // 2 * 2].reshape(-1, 2).max(axis=1) if len(d) >= 2 else np.zeros(1)
    np.save(cache, sec)
    return np.pad(sec, (0, max(0, n - len(sec))))[:n]

SPEECH_HYPE = re.compile(r"\b(oh my god|let'?s go+|no way|what the|holy|bro+|yo+|wow+|insane|crazy|run+|no no|"
                         r"yes+|dude|wait wait|look at|are you serious|omg|bhai|kya|arre|abe|dios|mano|caramba)\b", re.I)


def speech_series(job: Path, n: int) -> np.ndarray:
    """Hype words + talking speed from a fast full-stream transcript (whisper tiny, cached)."""
    from . import transcribe
    cache = job / "transcript_full.json"
    data = read_json(cache)
    if not data:
        log("transcribing the whole stream with whisper-tiny for the speech signal (a few minutes)...")
        data = transcribe.words(job / "audio.m4a", model="tiny")
        write_json(cache, data)
    x = np.zeros(n)
    for w in data["words"]:
        i = int(w["s"])
        if 0 <= i < n:
            x[i] += 0.25 + (2.0 if SPEECH_HYPE.search(w["w"]) else 0) + (0.5 if w["w"].endswith("!") else 0)
    return x


def score_job(job: Path, speech: bool = False, comments: bool = True, visual: bool = False) -> dict:
    j = read_json(job / "job.json")
    audio = job / "audio.m4a"
    log("measuring loudness per second...")
    db = loudness_series(audio)
    n = len(db)
    sig = {"loud": np.clip(smooth(rolling_z(db, 121), 3), -3, 6)}
    rows = chatmod.load(job)
    if rows:
        rate, hype = chat_series(rows, n)
        sig["chat"] = np.clip(rolling_z(smooth(rate, 10), 301), -3, 6)
        sig["hype"] = np.clip(rolling_z(smooth(hype, 10), 301), -3, 6)
    if comments:
        cs = comment_series(job, n)
        if cs.any():
            sig["comments"] = np.clip(rolling_z(smooth(cs, 3), 601), -3, 8)
    if visual:
        sig["visual"] = np.clip(rolling_z(smooth(visual_series(job, n), 3), 121), -3, 6)
    if speech:
        sig["speech"] = np.clip(rolling_z(smooth(speech_series(job, n), 8), 301), -3, 6)
    if j.get("heatmap"):
        sig["replay"] = np.clip(rolling_z(heatmap_series(j["heatmap"], n), 601), -3, 6)
    total = np.zeros(n)
    wsum = 0.0
    for k, v in sig.items():
        total += WEIGHTS[k] * v
        wsum += WEIGHTS[k]
    total = smooth(total / max(wsum, 1e-6), 5)
    np.save(job / "score.npy", np.vstack([total] + [sig[k] for k in sig]))
    write_json(job / "signals.json", {"signals": list(sig), "seconds": n, "chat_messages": len(rows)})
    return {"seconds": n, "signals": list(sig), "chat_messages": len(rows)}


def pick(job: Path, count: int = 8, length: float = 30.0, min_gap: float = 90.0,
         pre_ratio: float = 0.7, skip_start: float = 60.0) -> list[dict]:
    arr = np.load(job / "score.npy")
    meta = read_json(job / "signals.json")
    total = arr[0]
    names = meta["signals"]
    n = len(total)
    order = np.argsort(-total)
    chosen: list[int] = []
    j = read_json(job / "job.json") or {}
    stream = j.get("live_status") in ("was_live", "is_live") or j.get("live")
    # regular videos: skip the intro and the outro / end screen ("subscribe", credits)
    head = skip_start if stream else max(15.0, n * 0.03)
    tail = 5 if stream else max(30.0, n * 0.05)
    for i in order:
        if (total[i] <= 0.3 and len(chosen) >= count) or len(chosen) >= count * 3:
            break
        if i < head or i > n - tail:
            continue
        if all(abs(i - c) >= min_gap for c in chosen):
            chosen.append(int(i))
    moments = []
    for rank, peak in enumerate(sorted(chosen, key=lambda c: -total[c])[:count], 1):
        breakdown = {nm: round(float(arr[k + 1][peak]), 2) for k, nm in enumerate(names)}
        # chat reacts 5-15 s AFTER the moment: when chat drives the peak, shift the window earlier
        chat_led = max(breakdown.get("chat", 0), breakdown.get("hype", 0)) > max(breakdown.get("loud", 0),
                                                                                    breakdown.get("visual", 0)) + 1
        lag = 8.0 if chat_led else 0.0
        start = max(0.0, peak - lag - length * (0.8 if chat_led else pre_ratio))
        end = min(float(n), start + length + (lag / 2 if chat_led else 0))
        moments.append({
            "id": rank, "peak": peak, "start": round(start, 1), "end": round(end, 1),
            "score": round(float(total[peak]), 2), "signals": breakdown,
            "why": ", ".join(f"{k} spike" for k, v in breakdown.items() if v > 1.5) or "moderate activity",
            "status": "candidate",
        })
    write_json(job / "moments.json", moments)
    return moments


def window_chat(job: Path, start: float, end: float, limit: int = 25) -> list[str]:
    rows = [r for r in chatmod.load(job) if start <= r["t"] <= end]
    step = max(1, len(rows) // limit)
    return [r["text"] for r in rows[::step]][:limit]


def duration_ok(job: Path) -> float:
    return ffprobe_duration(job / "audio.m4a")
