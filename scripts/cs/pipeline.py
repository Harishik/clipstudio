"""Glue between steps: inspect candidates, cut, transcribe, render."""
from __future__ import annotations

from pathlib import Path

from . import fetch, posts, render, score, transcribe
from .util import die, hms, load_config, log, read_json, write_json


def clip_dir(job: Path, k: int | str) -> Path:
    return job / "clips" / f"{int(k):02d}"


def inspect(job: Path, ids: list[int] | None = None, frames_per: int = 6) -> list[dict]:
    """Frames + what was said + what chat said, for each candidate, so the agent can JUDGE before cutting."""
    j = read_json(job / "job.json")
    moments = read_json(job / "moments.json") or die("run `moments` first")
    out = []
    for m in moments:
        if ids and m["id"] not in ids:
            continue
        span = m["end"] - m["start"]
        ts = [m["start"] + span * (k + 0.5) / frames_per for k in range(frames_per)]
        pv = job / "previews" / f"m{m['id']:02d}"
        paths = fetch.frames(j["url"], ts, pv)
        sheet = fetch.contact_sheet(paths, job / "previews" / f"m{m['id']:02d}.jpg", [hms(t) for t in ts])
        said = transcribe.words(job / "audio.m4a", m["start"], m["end"], model="base")["text"]
        m.update(preview=str(sheet), said=said[:600], chat=score.window_chat(job, m["start"], m["end"] + 10))
        out.append(m)
    write_json(job / "moments.json", moments)
    return out


def cut(job: Path, k: int, start: float, end: float, max_height: int = 1080) -> Path:
    j = read_json(job / "job.json")
    d = clip_dir(job, k)
    d.mkdir(parents=True, exist_ok=True)
    raw = d / "raw.mp4"
    log(f"cutting {hms(start)}–{hms(end)} directly from the source (no full download)...")
    fetch.section(j["url"], start, end, raw, max_height)
    write_json(d / "clip.json", {"id": k, "start": start, "end": end, "source": j["webpage_url"]})
    return raw


def words_for(d: Path, language: str | None = None, force: bool = False, translate: bool = False) -> dict:
    p = d / "words.json"
    if p.exists() and not force:
        return read_json(p)
    w = transcribe.words(d / "raw.mp4", language=language, translate=translate)
    write_json(p, w)
    return w


def render_clip(job: Path, d: Path, **opts) -> dict:
    j = read_json(job / "job.json")
    cfg = load_config()
    w = read_json(opts.pop("captions_file")) if opts.get("captions_file") else words_for(d)
    opts.pop("captions_file", None)
    post = read_json(d / "post.json") or {}
    opts.setdefault("hook", post.get("hook", ""))
    opts.setdefault("title", post.get("title_on_video", ""))
    if opts.get("credit") is None:
        ch = j.get("channel") or ""
        opts["credit"] = (f"twitch.tv/{ch.lower()}" if j.get("platform") == "twitch" else f"YT: {ch}") if ch and \
            j.get("basis") != "own" else ""
    opts.setdefault("handle", cfg["brand"].get("watermark") or "")
    name = opts.pop("out_name", "final.mp4")
    res = render.render(d / "raw.mp4", d / name, words=w["words"], **opts)
    dur = res["duration"]
    title = opts.get("title") or opts.get("hook") or ""
    if title and name == "final.mp4":
        render.cover(d / name, min(dur * 0.4, dur - 0.5), title, d / "cover.jpg")
    meta = read_json(d / "clip.json", {}) or {}
    meta["render"] = {k: v for k, v in res.items()}
    write_json(d / "clip.json", meta)
    return res


def draft_render(job: Path, d: Path) -> dict:
    """Used by live mode: captions + auto layout, no hook yet (agent writes hooks/posts afterwards)."""
    return render_clip(job, d, layout="auto", music=None, hook="", title="")


def make_posts(job: Path, d: Path, platforms: list[str]) -> Path:
    j = read_json(job / "job.json")
    p = d / "post.json"
    if not p.exists():
        words_for(d)
        write_json(p, posts.skeleton(d, j, platforms))
    return p
