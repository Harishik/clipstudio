"""Live mode: record while they stream, cut the moment chat (or audio) explodes.

Why: by the time a VOD is downloaded and scanned, the best moments are already on every feed.
How (no account anywhere):
  streamlink/yt-dlp  -> ffmpeg segmenter (10 s .ts files, rolling buffer)
  anonymous chat     -> messages counted every 10 s vs the recent baseline
  audio loudness     -> each new segment measured vs the recent baseline
  spike              -> wait `post` seconds, stitch the segments, trim [t-pre, t+post] -> raw clip
                        (+ optional auto draft render with captions and auto layout)
"""
from __future__ import annotations

import collections
import json
import shutil
import signal
import statistics
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from . import chat as chatmod
from .util import (log, new_job, platform_of, run, streamlink_base, write_json, ytdlp_base)

SEG = 10


def _seg_db(p: Path) -> float:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-f", "s16le", "-ac", "1", "-ar", "8000", "-"],
                       capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if len(x) == 0:
        return -90.0
    # loudness of the loudest second in the segment
    n = len(x) // 8000
    if n == 0:
        return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))
    blk = x[: n * 8000].reshape(n, 8000)
    return float(np.max(20 * np.log10(np.sqrt(np.mean(blk ** 2, axis=1)) + 1e-9)))


class Live:
    def __init__(self, url: str, *, pre: float = 25, post: float = 8, mult: float = 2.5, min_msgs: int = 8,
                 cooldown: float = 60, keep_minutes: int = 20, max_hours: float = 6, quality: str = "1080p60,1080p,best",
                 audio_trigger: bool = True, auto_render: bool = False, basis: str = "permission", note: str = ""):
        self.url = url
        self.platform = platform_of(url)
        self.pre, self.post, self.mult, self.min_msgs = pre, post, mult, min_msgs
        self.cooldown, self.keep, self.max_hours = cooldown, keep_minutes, max_hours
        self.quality, self.audio_trigger, self.auto_render = quality, audio_trigger, auto_render
        name = url.rstrip("/").split("/")[-1].split("=")[-1]
        self.job = new_job(f"live-{name}")
        self.segdir = self.job / "segments"
        self.segdir.mkdir()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.buckets = collections.Counter()      # bucket index -> msg count
        self.hype = collections.Counter()
        self.recent_msgs = collections.deque(maxlen=400)
        self.t0 = time.time()
        self.moments: list[dict] = []
        self.last_fire = -1e9
        write_json(self.job / "job.json", {"url": url, "webpage_url": url, "platform": self.platform, "live": True,
                                           "title": f"LIVE {name}", "channel": name, "basis": basis,
                                           "basis_note": note, "created": time.strftime("%Y-%m-%dT%H:%M:%S")})

    # ---------------- recorder
    def _recorder(self):
        if self.platform == "twitch":
            src = streamlink_base() + ["--twitch-disable-ads", "--stdout", self.url, self.quality]
        else:
            src = streamlink_base() + ["--stdout", self.url, self.quality]
        if not shutil.which("streamlink") and self.platform == "youtube":
            src = ytdlp_base() + ["-f", "b[height<=720]/b", "-o", "-", self.url]
        seg = ["ffmpeg", "-v", "error", "-i", "pipe:0", "-c", "copy", "-f", "segment", "-segment_time", str(SEG),
               "-reset_timestamps", "1", str(self.segdir / "s_%06d.ts")]
        while not self.stop.is_set():
            p1 = subprocess.Popen(src, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p2 = subprocess.Popen(seg, stdin=p1.stdout, stderr=subprocess.DEVNULL)
            p1.stdout.close()
            while not self.stop.is_set() and p2.poll() is None:
                time.sleep(1)
            for p in (p1, p2):
                if p.poll() is None:
                    p.terminate()
            if self.stop.is_set():
                break
            log("stream ended or dropped — checking again in 30 s (Ctrl+C to quit)")
            for _ in range(30):
                if self.stop.is_set():
                    break
                time.sleep(1)

    def segments(self) -> list[tuple[Path, float, float]]:
        """(path, wall_start, wall_end) for finished segments (the newest is still being written)."""
        segs = sorted(self.segdir.glob("s_*.ts"))[:-1]
        out = []
        for s in segs:
            end = s.stat().st_mtime
            out.append((s, end - SEG, end))
        return out

    # ---------------- chat
    def _on_msg(self, t, user, text):
        b = int(t // SEG)
        with self.lock:
            self.buckets[b] += 1
            self.hype[b] += chatmod.hype_score(text)
            self.recent_msgs.append((t, text))

    def _chat(self):
        if self.platform == "twitch":
            login = self.url.rstrip("/").split("/")[-1]
            chatmod.twitch_irc(login, self._on_msg, self.stop)
        elif self.platform == "youtube":
            chatmod.youtube_live_tail(self.url, self.job / "chat_live", self._on_msg, self.stop)

    # ---------------- detector
    def _detect(self):
        seen_seg = set()
        seg_db = collections.deque(maxlen=60)
        while not self.stop.is_set():
            time.sleep(SEG)
            now_b = int((time.time() - self.t0) // SEG) - 1  # last complete bucket
            with self.lock:
                hist = [self.buckets.get(b, 0) for b in range(max(0, now_b - 30), now_b)]
                cur = self.buckets.get(now_b, 0)
                hy = self.hype.get(now_b, 0)
            base = statistics.median(hist) if hist else 0
            chat_spike = cur >= max(self.min_msgs, self.mult * max(base, 1)) and len(hist) >= 3
            audio_spike = False
            for s, ws, we in self.segments():
                if s in seen_seg:
                    continue
                seen_seg.add(s)
                db = _seg_db(s)
                if len(seg_db) >= 6 and self.audio_trigger:
                    mu, sd = float(np.mean(seg_db)), float(np.std(seg_db) + 1.0)
                    if db > mu + 2.2 * sd and db > -25:
                        audio_spike = True
                seg_db.append(db)
            print(f"[{time.strftime('%H:%M:%S')}] chat {cur:4d}/10s (base {base:.0f}) hype {hy:3d}"
                  f"{'  ** CHAT SPIKE **' if chat_spike else ''}{'  ** AUDIO SPIKE **' if audio_spike else ''}",
                  flush=True)
            if (chat_spike or audio_spike) and time.time() - self.last_fire > self.cooldown:
                self.last_fire = time.time()
                # chat reacts after the moment; anchor the moment slightly before the chat bucket
                anchor = time.time() - SEG - (4 if chat_spike else 0)
                reason = "chat" if chat_spike else "audio"
                threading.Thread(target=self._cut, args=(anchor, reason, cur, base), daemon=True).start()
            self._gc()
            if time.time() - self.t0 > self.max_hours * 3600:
                log("max hours reached")
                self.stop.set()

    def _cut(self, anchor: float, reason: str, cur: int, base: float):
        time.sleep(self.post + SEG + 2)
        a, b = anchor - self.pre, anchor + self.post
        segs = [s for s in self.segments() if s[2] > a and s[1] < b]
        if not segs:
            log("spike but no segments yet")
            return
        k = len(self.moments) + 1
        cdir = self.job / "clips" / f"{k:02d}"
        cdir.mkdir(parents=True, exist_ok=True)
        lst = cdir / "segs.txt"
        lst.write_text("".join(f"file '{s[0]}'\n" for s in segs))
        off = max(0.0, a - segs[0][1])
        raw = cdir / "raw.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-ss", f"{off:.2f}", "-t",
             f"{b - a:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
             str(raw)], check=False)
        with self.lock:
            msgs = [t for (tt, t) in self.recent_msgs if a - self.t0 <= tt <= b - self.t0 + 10][-30:]
        m = {"id": k, "reason": reason, "wall": time.strftime("%H:%M:%S", time.localtime(anchor)),
             "stream_offset": round(anchor - self.t0, 1), "chat_count": cur, "chat_base": base, "raw": str(raw),
             "chat_sample": msgs, "status": "raw"}
        self.moments.append(m)
        write_json(self.job / "moments.json", self.moments)
        write_json(cdir / "clip.json", m)
        print(f"CLIP {k:02d} saved -> {raw}  ({reason} spike)", flush=True)
        if self.auto_render:
            try:
                from . import pipeline
                pipeline.draft_render(self.job, cdir)
                print(f"CLIP {k:02d} draft rendered -> {cdir / 'final.mp4'}", flush=True)
            except SystemExit:
                log("auto render failed; raw clip kept")

    def _gc(self):
        keep_after = time.time() - self.keep * 60
        protect = {Path(x) for m in self.moments for x in [m.get("raw")]}
        for s, ws, we in self.segments():
            if we < keep_after and s not in protect:
                s.unlink(missing_ok=True)

    def run(self, signals: bool = True):
        print(f"LIVE job: {self.job}", flush=True)
        threads = [threading.Thread(target=f, daemon=True) for f in (self._recorder, self._chat, self._detect)]
        for t in threads:
            t.start()
        if signals:
            signal.signal(signal.SIGINT, lambda *_: self.stop.set())
            signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        try:
            while not self.stop.is_set():
                time.sleep(1)
        finally:
            self.stop.set()
            time.sleep(2)
            write_json(self.job / "moments.json", self.moments)
            print(json.dumps({"job": str(self.job), "clips": len(self.moments)}), flush=True)
