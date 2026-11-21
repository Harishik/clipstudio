#!/usr/bin/env python3
"""ClipStudio — live + recorded Twitch/YouTube clipping, vertical editing and multi-platform posting.

Run `python3 scripts/clipstudio.py -h` for commands. Every command prints JSON on stdout (logs go to stderr),
so any coding agent can drive it.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cs import chat, discover, fetch, pipeline, posts, publish, score  # noqa: E402
from cs.captions import PRESETS as _PRESETS  # noqa: E402
from cs.util import (SKILL_ROOT, config_path, die, have, job_dir, load_config, log, parse_time,  # noqa: E402
                     print_json, read_json, workspace, write_json)


STYLES = list(_PRESETS)


def _ids(s):
    return [int(x) for x in s.split(",")] if s else None


def _plats(s):
    return [p.strip().lower() for p in (s or ",".join(load_config()["post"]["platforms"])).split(",") if p.strip()]


# ---------------------------------------------------------------- commands
def c_doctor(a):
    mods = {}
    for m in ["yt_dlp", "streamlink", "faster_whisper", "PIL", "numpy", "requests", "cv2", "playwright"]:
        try:
            __import__(m)
            mods[m] = True
        except ImportError:
            mods[m] = False
    print_json({"ffmpeg": have("ffmpeg"), "ffprobe": have("ffprobe"), "node_or_deno": have("node") or have("deno"),
                "python_modules": mods, "config": str(config_path()),
                "config_exists": config_path().exists(), "workspace": str(workspace()),
                "posting_profile": Path("~/.clipstudio/browser-profile").expanduser().exists()})


def c_setup(a):
    p = config_path()
    if p.exists() and not a.force:
        print_json({"config": str(p), "status": "exists"})
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SKILL_ROOT / "config.example.toml", p)
    print_json({"config": str(p), "status": "created", "next": "edit it (handle, platforms, timezone), then `doctor`"})


def c_streams(a):
    print_json(discover.streams(a.game, a.limit, a.lang))


def c_trends(a):
    print_json(discover.trends(a.query, a.hours, a.limit))


def c_videos(a):
    print_json(discover.videos(a.query, a.min, a.max, a.sort, a.limit, a.days or None))


def c_vods(a):
    print_json(discover.vods(a.channel, a.limit))


def c_new(a):
    d = fetch.create_job(a.url, a.basis, a.note or "", a.campaign)
    j = read_json(d / "job.json")
    print_json({"job": d.name, "path": str(d), "title": j["title"], "channel": j["channel"],
                "duration": j["duration"], "live_status": j["live_status"], "has_live_chat": j["has_live_chat"],
                "has_heatmap": bool(j["heatmap"])})


def c_moments(a):
    d = job_dir(a.job)
    fetch.audio(d)
    if not (d / "chat.jsonl").exists() and not a.no_chat:
        n = chat.fetch_replay(d)
        log(f"chat messages: {n}")
    if not (d / "score.npy").exists() or a.rescore:
        j = read_json(d / "job.json")
        has_chat = (d / "chat.jsonl").exists() and (d / "chat.jsonl").stat().st_size > 0
        visual = a.visual or (not has_chat and (j.get("duration") or 0) <= 4 * 3600 and not a.no_visual)
        score.score_job(d, speech=a.speech, comments=not a.no_comments, visual=visual)
    print_json(score.pick(d, a.count, a.length, a.gap))


def c_inspect(a):
    print_json(pipeline.inspect(job_dir(a.job), _ids(a.ids)))


def c_cut(a):
    d = job_dir(a.job)
    if a.moment:
        m = next((m for m in read_json(d / "moments.json") or [] if m["id"] == a.moment), None) or die("no such moment")
        start, end = m["start"], m["end"]
        k = a.id or a.moment
    else:
        if a.start is None or a.end is None:
            die("give --moment N or --start/--end")
        start, end = parse_time(a.start), parse_time(a.end)
        existing = list((d / "clips").glob("*")) if (d / "clips").exists() else []
        k = a.id or len(existing) + 1
    start, end = max(0, start - a.pad), end + a.pad
    raw = pipeline.cut(d, k, start, end, a.max_height)
    w = pipeline.words_for(raw.parent, a.lang)
    print_json({"clip": k, "raw": str(raw), "start": start, "end": end, "transcript": w["text"]})


def c_transcribe(a):
    d = pipeline.clip_dir(job_dir(a.job), a.clip)
    w = pipeline.words_for(d, a.lang, force=True, translate=a.translate)
    print_json({"words": len(w["words"]), "language": w["language"], "text": w["text"]})


def c_render(a):
    job = job_dir(a.job)
    d = pipeline.clip_dir(job, a.clip)
    cam = None
    if a.facecam:
        x, y, w, h = [int(v) for v in a.facecam.split(",")]
        cam = {"x": x, "y": y, "w": w // 2 * 2, "h": h // 2 * 2}
    opts = dict(layout=a.layout, cam=cam, focus=a.focus, music=a.music, progress=a.progress,
                caption_style=a.style, max_words=a.words, accent=a.accent, cta=a.cta or "",
                captions_file=a.captions_file, out_name=a.out or "final.mp4", tighten=not a.no_tighten,
                auto_punch=not a.no_auto_punch, emoji=a.emoji, sfx="off" if a.no_sfx else a.sfx, cap_size=a.cap_size,
                headline_style=a.headline_style, do_censor=not a.no_censor, grade=not a.no_grade,
                zoomcuts=not a.no_zoomcuts, tease=a.tease or False)
    if a.trim:
        s, e = a.trim.split(",")
        opts["trim"] = (parse_time(s), parse_time(e))
    if a.punch:
        opts["punch"] = [parse_time(x) for x in a.punch.split(",")]
    for k in ("hook", "title", "credit", "handle"):
        v = getattr(a, k)
        if v is not None:
            opts[k] = v
    if a.hook_secs is not None:
        opts["hook_secs"] = a.hook_secs
    if a.music_db is not None:
        opts["music_db"] = a.music_db
    print_json(pipeline.render_clip(job, d, **opts))


def clip_count(v):
    n = int(v)
    if n < 1:
        raise argparse.ArgumentTypeError("make at least 1 clip")
    return n


def c_styles(a):
    from cs import captions
    d = pipeline.clip_dir(job_dir(a.job), a.clip)
    fr = d / "styles_frame.jpg"
    src = d / "raw.mp4"
    import subprocess
    vf = ["-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(parse_time(a.t)), "-i", str(src), "-frames:v", "1", *vf,
                    str(fr)], check=True)
    out = captions.preview_sheet(d / "styles.jpg", fr)
    print_json({"styles": STYLES, "preview": str(out),
                "use": f"clipstudio render {a.job} {a.clip} --style <name>"})


def c_make(a):
    d = fetch.create_job(a.url, a.basis, a.note or "")
    fetch.audio(d)
    if not (d / "chat.jsonl").exists():
        chat.fetch_replay(d)
    j = read_json(d / "job.json")
    has_chat = (d / "chat.jsonl").exists() and (d / "chat.jsonl").stat().st_size > 0
    score.score_job(d, speech=a.speech, comments=True, visual=not has_chat and (j.get("duration") or 0) <= 4 * 3600)
    length = min(max(a.length, 12), 90)
    dur_s = float(j.get("duration") or 0) or 3600
    gap = max(length + 5, min(max(60, length * 2), dur_s / max(1, a.clips) * 0.8))   # many clips -> tighter spacing
    ms = score.pick(d, a.clips, length, min_gap=gap)
    plats = _plats(a.platforms)
    out = []
    for m in ms[: a.clips]:
        pipeline.cut(d, m["id"], m["start"], m["end"])
        cd = pipeline.clip_dir(d, m["id"])
        res = pipeline.render_clip(d, cd, layout=a.layout, caption_style=a.style, music=a.music)
        pipeline.make_posts(d, cd, plats)
        out.append({"clip": m["id"], "video": res["out"], "signals": m["signals"], "start": m["start"]})
    gal = make_gallery(d)
    print_json({"job": d.name, "made": len(out), "asked": a.clips, "clips": out, "gallery": gal,
                "next": "review each clip, write hooks/titles + post.json, re-render with --hook/--title/--punch, "
                        "then check -> queue"})


def make_gallery(d):
    from PIL import Image
    import subprocess
    finals = sorted((d / "clips").glob("*/final.mp4"))
    if not finals:
        return None
    tiles = []
    for f in finals:
        t = f.parent / "thumb.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2.5", "-i", str(f), "-frames:v", "1", "-vf",
                        "scale=270:480", str(t)], check=False)
        if t.exists():
            tiles.append(Image.open(t))
    cols = min(6, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    g = Image.new("RGB", (270 * cols, 480 * rows), "black")
    for i, im in enumerate(tiles):
        g.paste(im, ((i % cols) * 270, (i // cols) * 480))
    out = d / "gallery.jpg"
    g.save(out, quality=88)
    return str(out)


def c_gallery(a):
    print_json({"gallery": make_gallery(job_dir(a.job))})


def c_hooks(a):
    from cs import hooks
    job = job_dir(a.job)
    print_json(hooks.context(job, pipeline.clip_dir(job, a.clip)))


def c_hookcheck(a):
    from cs import hooks
    print_json([{"text": t, **hooks.score(t, a.kind)} for t in a.text])


def c_frame(a):
    """Grab a frame of a clip (to locate the facecam or check a layout by eye)."""
    d = pipeline.clip_dir(job_dir(a.job), a.clip)
    src = d / (a.file or "raw.mp4")
    out = d / f"frame_{a.t}.jpg"
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(parse_time(a.t)), "-i", str(src), "-frames:v", "1",
                    str(out)], check=True)
    from cs.util import ffprobe_size
    w, h = ffprobe_size(src)
    print_json({"frame": str(out), "width": w, "height": h})


def c_posts(a):
    job = job_dir(a.job)
    d = pipeline.clip_dir(job, a.clip)
    p = pipeline.make_posts(job, d, _plats(a.platforms))
    print_json({"post_json": str(p), "fill_this": read_json(p)})


def c_check(a):
    job = job_dir(a.job)
    d = pipeline.clip_dir(job, a.clip)
    j = read_json(job / "job.json")
    rules = read_json(Path(a.rules)) if a.rules else (read_json(Path(j["campaign"])) if j.get("campaign") else None)
    print_json(posts.check(d, j, _plats(a.platforms) if a.platforms else None, rules))


def c_queue(a):
    d = pipeline.clip_dir(job_dir(a.job), a.clip)
    print_json(publish.enqueue(d, _plats(a.platforms), a.at, a.account))


def c_approve(a):
    print_json({"approved": publish.approve(a.ids.split(","))})


def c_publish(a):
    print_json(publish.publish(due_only=not a.now, item_ids=a.ids.split(",") if a.ids else None, dry=a.dry,
                               headless=True if a.headless else None))


def c_list(a):
    q = publish.load_q()
    if not a.all:
        q = [i for i in q if i["status"] not in ("posted", "exported")]
    print_json([{k: i.get(k) for k in ("id", "platform", "status", "scheduled_at", "clip", "url", "error")} for i in q])


def c_login(a):
    from cs import browser_post
    print_json(browser_post.login(a.platform, a.wait))


def c_stats(a):
    print_json(publish.refresh_stats())


def c_jobs(a):
    root = workspace() / "jobs"
    rows = []
    for d in sorted(root.glob("*"))[-a.limit:] if root.exists() else []:
        j = read_json(d / "job.json") or {}
        rows.append({"job": d.name, "title": j.get("title"), "platform": j.get("platform"),
                     "clips": len(list((d / "clips").glob("*"))) if (d / "clips").exists() else 0})
    print_json(rows)


def c_live(a):
    from cs.live import Live
    Live(a.url, pre=a.pre, post=a.post, mult=a.mult, min_msgs=a.min_msgs, cooldown=a.cooldown,
         keep_minutes=a.keep, max_hours=a.max_hours, quality=a.quality, audio_trigger=not a.no_audio,
         auto_render=a.auto_render, basis=a.basis, note=a.note or "").run()


def c_daily(a):
    from cs import daily
    print_json(daily.run_daily(a.minutes, a.no_live, a.no_videos, a.auto_copy, a.basis, a.clips))
    if a.publish:
        print_json(publish.publish())


def c_auto(a):
    """One-shot for a recorded stream: job -> moments -> cut top N -> draft renders. The agent should still judge."""
    d = fetch.create_job(a.url, a.basis, a.note or "", a.campaign)
    fetch.audio(d)
    chat.fetch_replay(d)
    score.score_job(d)
    ms = score.pick(d, a.count, a.length)
    out = []
    for m in ms[: a.count]:
        pipeline.cut(d, m["id"], m["start"], m["end"])
        res = pipeline.draft_render(d, pipeline.clip_dir(d, m["id"]))
        out.append({"moment": m, "render": res})
    print_json({"job": d.name, "clips": out})


# ---------------------------------------------------------------- parser
def main(argv=None):
    p = argparse.ArgumentParser(prog="clipstudio", description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("doctor").set_defaults(f=c_doctor)
    s = sp.add_parser("setup")
    s.add_argument("--force", action="store_true")
    s.set_defaults(f=c_setup)

    s = sp.add_parser("streams", help="who is live now (Twitch + YouTube), no login")
    s.add_argument("--game", default="gta 6")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--lang")
    s.set_defaults(f=c_streams)
    s = sp.add_parser("trends", help="YouTube uploads ranked by views/hour")
    s.add_argument("--query", default="GTA 6")
    s.add_argument("--hours", type=int, default=24)
    s.add_argument("--limit", type=int, default=15)
    s.set_defaults(f=c_trends)
    s = sp.add_parser("videos", help="ANY YouTube video to clip (gameplay, walkthroughs, funny moments), by length")
    s.add_argument("--query", default="GTA 6 gameplay")
    s.add_argument("--min", type=float, default=3, help="minimum minutes")
    s.add_argument("--max", type=float, default=600, help="maximum minutes")
    s.add_argument("--sort", default="views", choices=["views", "date", "relevance"])
    s.add_argument("--days", type=int, default=7, help="uploaded within: 1, 7, 30, 365 (0 = any time)")
    s.add_argument("--limit", type=int, default=15)
    s.set_defaults(f=c_videos)
    s = sp.add_parser("vods", help="recent recorded streams of a channel")
    s.add_argument("channel")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(f=c_vods)

    s = sp.add_parser("new", help="create a job for a recorded stream / video / local file")
    s.add_argument("url")
    s.add_argument("--basis", required=True, choices=list(fetch.BASIS))
    s.add_argument("--note")
    s.add_argument("--campaign", help="campaign rules JSON file")
    s.set_defaults(f=c_new)

    s = sp.add_parser("moments", help="audio-only download + chat replay + scoring -> candidates")
    s.add_argument("job")
    s.add_argument("--count", type=int, default=8)
    s.add_argument("--length", type=float, default=30)
    s.add_argument("--gap", type=float, default=90)
    s.add_argument("--no-chat", action="store_true")
    s.add_argument("--rescore", action="store_true")
    s.add_argument("--speech", action="store_true", help="add a speech-hype signal (use when there is no chat)")
    s.add_argument("--visual", action="store_true", help="add on-screen action signal (auto when there is no chat)")
    s.add_argument("--no-visual", action="store_true")
    s.add_argument("--no-comments", action="store_true", help="skip timestamped-comment signal (YouTube)")
    s.set_defaults(f=c_moments)
    s = sp.add_parser("inspect", help="frames + transcript + chat per candidate, for judging")
    s.add_argument("job")
    s.add_argument("--ids")
    s.set_defaults(f=c_inspect)

    s = sp.add_parser("cut", help="cut a section straight from the source")
    s.add_argument("job")
    s.add_argument("--moment", type=int)
    s.add_argument("--start")
    s.add_argument("--end")
    s.add_argument("--id", type=int)
    s.add_argument("--pad", type=float, default=0)
    s.add_argument("--max-height", type=int, default=1080)
    s.add_argument("--lang")
    s.set_defaults(f=c_cut)
    s = sp.add_parser("transcribe", help="(re)make word captions; --translate = English captions from any language")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.add_argument("--lang", help="spoken language code (hi, es, pt...) or auto")
    s.add_argument("--translate", action="store_true")
    s.set_defaults(f=c_transcribe)
    s = sp.add_parser("frame", help="grab one frame of a clip")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.add_argument("--t", default="1")
    s.add_argument("--file")
    s.set_defaults(f=c_frame)

    s = sp.add_parser("render", help="vertical edit with captions, hook, title, credit, music")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.add_argument("--layout", default="auto", choices=["auto", "fill", "blur", "facecam", "track"])
    s.add_argument("--facecam", help="x,y,w,h of the webcam in the source frame")
    s.add_argument("--focus", type=float, default=0.5, help="horizontal crop focus 0..1")
    s.add_argument("--trim", help="start,end inside the raw clip (seconds)")
    s.add_argument("--hook", help="headline; wrap words in *stars* to colour them")
    s.add_argument("--hook-secs", type=float, help="seconds the hook shows before the title (default 3.5; 0 = whole clip)")
    s.add_argument("--title")
    s.add_argument("--credit")
    s.add_argument("--handle")
    s.add_argument("--cta")
    s.add_argument("--music", help="'phonk' | 'trap' | 'chill' (original beats), 'auto', a file/folder, or 'none'")
    s.add_argument("--music-db", type=float)
    s.add_argument("--punch", help="comma list of seconds (raw-clip time) to punch-zoom")
    s.add_argument("--style", choices=STYLES + ["auto", "pop", "plain", "none"],
                   help="caption style (see `clipstudio styles`); default auto = best style for this clip")
    s.add_argument("--words", type=int, help="max words per caption chunk")
    s.add_argument("--accent")
    s.add_argument("--captions-file", help="words JSON (e.g. translated) to use instead of whisper")
    s.add_argument("--out", help="output filename inside the clip folder")
    s.add_argument("--progress", action="store_true", help="thin progress bar at the bottom")
    s.add_argument("--no-tighten", action="store_true", help="keep dead air (default: cut it)")
    s.add_argument("--no-auto-punch", action="store_true", help="no automatic zoom/shake/flash on loud peaks")
    s.add_argument("--emoji", default="auto", help="'auto', 'none' or one emoji to pop on impact moments")
    s.add_argument("--no-sfx", action="store_true")
    s.add_argument("--sfx", default="auto", choices=["auto", "minimal", "off"],
                   help="auto = whoosh/hit on hook, riser->boom on impacts, whips on zoom cuts, pops; minimal = hook+impacts")
    s.add_argument("--cap-size", type=int, help="caption font px (default 74)")
    s.add_argument("--headline-style", default="auto", choices=["auto", "top", "outline", "box"],
                   help="auto: persistent yellow question at the top (no facecam) / on the seam (facecam)")
    s.add_argument("--tease", nargs="?", const="WAIT FOR IT 👀", default=None,
                   help="cold open: flash the payoff first (optional text), then play the clip")
    s.add_argument("--no-censor", action="store_true", help="show swear words uncensored in captions")
    s.add_argument("--no-grade", action="store_true")
    s.add_argument("--no-zoomcuts", action="store_true", help="no alternating punch-in framing between phrases")
    s.set_defaults(f=c_render)

    s = sp.add_parser("hooks", help="hook-writing pack: transcript, chat + comments at this moment, formulas")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.set_defaults(f=c_hooks)
    s = sp.add_parser("hookcheck", help="score hooks / titles (0-100) with fixes")
    s.add_argument("text", nargs="+")
    s.add_argument("--kind", default="hook", choices=["hook", "title"])
    s.set_defaults(f=c_hookcheck)

    s = sp.add_parser("styles", help="preview every caption style on a frame of your clip, to pick one")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.add_argument("--t", default="2")
    s.set_defaults(f=c_styles)

    s = sp.add_parser("make", help="one command: N clips from a VOD/video -> rendered + post skeletons")
    s.add_argument("url")
    s.add_argument("--clips", type=clip_count, default=3, help="how many clips to make (any number; limited only by the source length and your machine)")
    s.add_argument("--length", type=float, default=30, help="target seconds per clip (15-60)")
    s.add_argument("--basis", default="transformative", choices=list(fetch.BASIS))
    s.add_argument("--note")
    s.add_argument("--style", choices=STYLES + ["auto"], default="auto", help="caption style or auto (picked per clip)")
    s.add_argument("--layout", default="auto", choices=["auto", "fill", "blur", "facecam", "track"])
    s.add_argument("--music", default="none")
    s.add_argument("--platforms")
    s.add_argument("--speech", action="store_true")
    s.set_defaults(f=c_make)

    s = sp.add_parser("gallery", help="one image showing every finished clip of a job, for quick review")
    s.add_argument("job")
    s.set_defaults(f=c_gallery)

    s = sp.add_parser("posts", help="write post.json skeleton for the agent to fill")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.add_argument("--platforms")
    s.set_defaults(f=c_posts)
    s = sp.add_parser("check", help="rule-check video + copy (+ campaign rules)")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.add_argument("--rules")
    s.add_argument("--platforms")
    s.set_defaults(f=c_check)
    s = sp.add_parser("queue", help="schedule a checked clip to platforms")
    s.add_argument("job")
    s.add_argument("clip", type=int)
    s.add_argument("--platforms")
    s.add_argument("--at", help="ISO datetime; default = next free slot per platform")
    s.add_argument("--account", help="label of the account this goes to (informational)")
    s.set_defaults(f=c_queue)
    s = sp.add_parser("approve")
    s.add_argument("ids", help="comma ids or 'all'")
    s.set_defaults(f=c_approve)
    s = sp.add_parser("publish", help="post approved items that are due, through your browser session")
    s.add_argument("--now", action="store_true", help="post approved items now, ignoring their time slot")
    s.add_argument("--headless", action="store_true", help="no visible browser window")
    s.add_argument("--ids")
    s.add_argument("--dry", action="store_true")
    s.set_defaults(f=c_publish)
    s = sp.add_parser("list", help="show the posting queue")
    s.add_argument("--all", action="store_true")
    s.set_defaults(f=c_list)
    s = sp.add_parser("login", help="sign in once (yourself) in the ClipStudio browser profile used for posting")
    s.add_argument("platform", choices=["youtube", "tiktok", "instagram", "x", "facebook"])
    s.add_argument("--wait", type=int, default=10, help="minutes to keep the window open")
    s.set_defaults(f=c_login)
    sp.add_parser("stats", help="refresh public view counts of posted clips").set_defaults(f=c_stats)
    s = sp.add_parser("jobs")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(f=c_jobs)

    s = sp.add_parser("live", help="record a live stream and cut clips on chat/audio spikes")
    s.add_argument("url")
    s.add_argument("--pre", type=float, default=25)
    s.add_argument("--post", type=float, default=8)
    s.add_argument("--mult", type=float, default=2.5, help="chat spike = this x baseline")
    s.add_argument("--min-msgs", type=int, default=8, help="min msgs per 10 s to count as a spike")
    s.add_argument("--cooldown", type=float, default=60)
    s.add_argument("--keep", type=int, default=20, help="minutes of rolling buffer")
    s.add_argument("--max-hours", type=float, default=6)
    s.add_argument("--quality", default="1080p60,1080p,best")
    s.add_argument("--no-audio", action="store_true", help="chat spikes only")
    s.add_argument("--auto-render", action="store_true")
    s.add_argument("--basis", default="permission", choices=list(fetch.BASIS))
    s.add_argument("--note")
    s.set_defaults(f=c_live)

    s = sp.add_parser("daily", help="autopilot for scheduled tasks: live clipping + top new videos -> drafts")
    s.add_argument("--minutes", type=float, help="minutes of live recording (default [daily] live_minutes)")
    s.add_argument("--no-live", action="store_true")
    s.add_argument("--no-videos", action="store_true")
    s.add_argument("--auto-copy", action="store_true", help="no agent: generate simple hooks/posts and queue them")
    s.add_argument("--clips", type=clip_count, help="clips per source today (default [daily] clips_per_source)")
    s.add_argument("--publish", action="store_true", help="then post whatever is approved and due")
    s.add_argument("--basis", default="transformative", choices=list(fetch.BASIS))
    s.set_defaults(f=c_daily)

    s = sp.add_parser("auto", help="recorded stream end-to-end draft (no posting)")
    s.add_argument("url")
    s.add_argument("--basis", required=True, choices=list(fetch.BASIS))
    s.add_argument("--note")
    s.add_argument("--campaign")
    s.add_argument("--count", type=clip_count, default=3)
    s.add_argument("--length", type=float, default=30)
    s.set_defaults(f=c_auto)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
