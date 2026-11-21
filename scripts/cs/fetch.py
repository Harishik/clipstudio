"""Fetching without logging in: metadata, audio-only, exact sections, preview frames.

Key idea: never download a whole multi-hour stream. We pull audio only for scoring,
then cut only the seconds we need straight from the remote stream with ffmpeg input seeking.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import twitch
from .util import (die, ffprobe_duration, log, new_job, platform_of, read_json, run, write_json,
                   ytdlp_base)

BASIS = {
    "campaign": "Clipping campaign (Whop/Clipster/etc). Follow the campaign's rules file.",
    "permission": "Streamer/creator publicly allows clipping (note where they said it).",
    "own": "My own stream/footage.",
    "transformative": "Commentary/ranking/story added on top (fair-use style transformation).",
}


def info(url: str) -> dict:
    if platform_of(url) == "local":
        return {"title": Path(url).stem, "duration": ffprobe_duration(Path(url)), "webpage_url": str(Path(url).resolve()),
                "extractor": "local", "live_status": "not_live"}
    r = run(ytdlp_base() + ["-J", "--skip-download", url], check=False)
    if (r.returncode != 0 or not r.stdout.strip()) and twitch.vod_id(url):
        log("yt-dlp can't see this Twitch VOD anonymously -> using the built-in Twitch resolver")
        return twitch.info(url)
    if r.returncode != 0 or not r.stdout.strip():
        die(f"could not read {url}: {r.stderr[-600:]}")
    return json.loads(r.stdout)


def create_job(url: str, basis: str, basis_note: str = "", campaign: str | None = None) -> Path:
    if basis not in BASIS:
        die(f"--basis must be one of {list(BASIS)}")
    i = info(url)
    d = new_job(i.get("title") or "stream")
    job = {
        "url": url,
        "webpage_url": i.get("webpage_url") or url,
        "platform": platform_of(url),
        "title": i.get("title"),
        "channel": i.get("channel") or i.get("uploader") or i.get("uploader_id"),
        "channel_url": i.get("channel_url") or i.get("uploader_url"),
        "duration": i.get("duration"),
        "live_status": i.get("live_status"),
        "has_live_chat": "live_chat" in (i.get("subtitles") or {}),
        "extractor": i.get("extractor"),
        "heatmap": i.get("heatmap") or [],
        "chapters": i.get("chapters") or [],
        "basis": basis,
        "basis_note": basis_note,
        "campaign": campaign,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(d / "job.json", job)
    (d / "PERMISSION.md").write_text(
        f"# Clipping basis\n\n- Source: {job['webpage_url']}\n- Channel: {job['channel']}\n"
        f"- Basis: **{basis}** — {BASIS[basis]}\n- Note: {basis_note or '(none)'}\n"
        f"- Campaign: {campaign or '(none)'}\n- Recorded: {job['created']}\n", encoding="utf-8")
    return d


def audio(job: Path) -> Path:
    j = read_json(job / "job.json")
    out = job / "audio.m4a"
    if out.exists():
        return out
    if j["platform"] == "local":
        run(["ffmpeg", "-v", "error", "-y", "-i", j["url"], "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k", str(out)])
        return out
    log("downloading audio only (a 3h stream is ~70–150 MB instead of many GB)...")
    if j.get("extractor") == "twitch-anon" or (twitch.vod_id(j["url"]) and j["platform"] == "twitch"):
        try:
            a_url = twitch.media_urls(j["url"], audio_only=True)
            run(["ffmpeg", "-v", "error", "-y", "-i", a_url, "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k", str(out)])
            return out
        except SystemExit:
            log("built-in Twitch audio fetch failed, trying yt-dlp")
    tmpl = str(job / "audio.%(ext)s")
    r = run(ytdlp_base() + ["-f", "ba[ext=m4a]/ba/Audio_Only/worst", "-o", tmpl, j["url"]], check=False, capture=True)
    got = sorted(job.glob("audio.*"))
    if not got:
        die(f"audio download failed: {r.stderr[-800:]}")
    src = got[0]
    if src.suffix != ".m4a":
        run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k", str(out)])
        src.unlink(missing_ok=True)
    return out


def stream_urls(url: str, max_height: int = 1080) -> tuple[str, str | None]:
    """Direct media URLs (video, audio-or-None) for remote seeking. Nothing is saved."""
    if platform_of(url) == "local":
        return url, None
    if twitch.vod_id(url):
        r = run(ytdlp_base() + ["-g", "-f", f"b[height<={max_height}]/b", url], check=False)
        if r.returncode != 0 or not r.stdout.startswith("http"):
            return twitch.media_urls(url, max_height), None
    fmt = f"bv*[height<={max_height}][vcodec^=avc1]+ba/bv*[height<={max_height}]+ba/b[height<={max_height}]/b"
    r = run(ytdlp_base() + ["-g", "-f", fmt, url])
    lines = [x for x in r.stdout.strip().splitlines() if x.startswith("http")]
    if not lines:
        die("no stream url")
    return lines[0], (lines[1] if len(lines) > 1 else None)


def section(url: str, start: float, end: float, out: Path, max_height: int = 1080) -> Path:
    """Cut [start,end] straight from the remote stream (or local file) — frame-accurate, small."""
    v, a = stream_urls(url, max_height)
    dur = end - start
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", v]
    if a:
        cmd += ["-ss", f"{start:.3f}", "-i", a, "-map", "0:v:0", "-map", "1:a:0"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
    cmd += ["-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        r = run(cmd, check=False)
        if r.returncode == 0 and out.exists() and ffprobe_duration(out) > dur * 0.8:
            return out
        log(f"section retry {attempt + 1}: {r.stderr[-300:]}")
        time.sleep(2)
        v, a = stream_urls(url, max_height)  # signed URLs can expire
        cmd[cmd.index("-i") + 1] = v
    die("could not cut section")


def frames(url: str, times: list[float], out_dir: Path, height: int = 360) -> list[Path]:
    """Grab single frames at given timestamps without downloading the video."""
    v, _ = stream_urls(url, max_height=480)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in times:
        p = out_dir / f"f_{int(t * 10):08d}.jpg"
        if not p.exists():
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(t, 0):.2f}", "-i", v, "-frames:v", "1",
                 "-vf", f"scale=-2:{height}", "-q:v", "4", str(p)], check=False)
        if p.exists():
            paths.append(p)
    return paths


def contact_sheet(paths: list[Path], out: Path, labels: list[str] | None = None, cols: int = 3) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    from .util import body_font_path
    ims = [Image.open(p).convert("RGB") for p in paths]
    if not ims:
        die("no frames to tile")
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), "black")
    f = ImageFont.truetype(body_font_path(), 22)
    for i, im in enumerate(ims):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(im.resize((w, h)), (x, y))
        if labels:
            d = ImageDraw.Draw(sheet)
            d.rectangle([x, y, x + 140, y + 32], fill=(0, 0, 0))
            d.text((x + 8, y + 4), labels[i], fill=(255, 230, 0), font=f)
    sheet.save(out, quality=85)
    return out
