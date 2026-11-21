"""Daily autopilot: what a scheduled task (Claude / Codex / Gemini / cron) runs every day.

1. LIVE   — your preferred channels first, else the biggest live streams for the game: record + auto-clip on chat/audio
            spikes for `live_minutes`, drafts rendered as they happen (several streams in parallel).
2. VIDEOS — today's/this week's most-viewed new YouTube videos for the query (gameplay, walkthroughs, funny moments,
            finished streams): score with chat replay + timestamped comments + on-screen action + loudness, cut the
            best moments, render drafts.
3. REPORT — `daily_report.json` listing every draft with its transcript, so the agent can judge, write hooks/posts,
            re-render and queue. With --auto-copy (no agent), simple hooks/posts are generated and queued.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import re
import threading
from pathlib import Path

from . import chat, discover, fetch, pipeline, posts, publish, score
from .util import load_config, log, read_json, run, workspace, write_json, ytdlp_base


def _history() -> dict:
    return read_json(workspace() / "history.json", {"urls": []}) or {"urls": []}


def _is_live(url: str) -> bool:
    if "twitch.tv" in url:
        try:
            return bool(discover.twitch_channel(url.rstrip("/").split("/")[-1]).get("stream"))
        except Exception:  # noqa: BLE001
            return False
    u = url.rstrip("/")
    if "youtube.com/@" in u and not u.endswith("/live"):
        u += "/live"
    r = run(ytdlp_base() + ["-J", "--skip-download", u], check=False)
    try:
        return (json.loads(r.stdout) or {}).get("live_status") == "is_live"
    except (json.JSONDecodeError, AttributeError):
        return False


def live_targets(cfg: dict) -> list[str]:
    out = [c for c in cfg.get("channels", []) if _is_live(c)]
    if len(out) < cfg["max_streams"]:
        for s in discover.streams(cfg["game"], 10, cfg.get("lang") or None):
            if (s.get("viewers") or 0) >= cfg["min_viewers"] and s["url"] not in out:
                out.append(s["url"])
            if len(out) >= cfg["max_streams"]:
                break
    return out[: cfg["max_streams"]]


def run_live(urls: list[str], minutes: float, basis: str) -> list[Path]:
    from .live import Live
    lives = [Live(u, max_hours=minutes / 60, auto_render=True, basis=basis, note="daily autopilot",
                  min_msgs=6, mult=2.5, cooldown=90) for u in urls]
    th = [threading.Thread(target=lv.run, kwargs={"signals": False}, daemon=True) for lv in lives]
    for t in th:
        t.start()
    for t in th:
        t.join(timeout=minutes * 60 + 300)
    return [lv.job for lv in lives]


def run_videos(cfg: dict, basis: str, hist: dict) -> list[Path]:
    jobs = []
    cands = discover.videos(cfg["video_query"], 4, 600, "views", 20, days=2) or \
        discover.videos(cfg["video_query"], 4, 600, "views", 20, days=7)
    for v in cands:
        if len(jobs) >= cfg["videos_per_day"]:
            break
        if v["url"] in hist["urls"]:
            continue
        try:
            d = fetch.create_job(v["url"], basis, "daily autopilot")
            fetch.audio(d)
            chat.fetch_replay(d)
            j = read_json(d / "job.json")
            score.score_job(d, comments=True, visual=(j.get("duration") or 0) <= 4 * 3600)
            ms = score.pick(d, cfg["clips_per_source"], 32)
            for m in ms[: cfg["clips_per_source"]]:
                pipeline.cut(d, m["id"], m["start"], m["end"])
                pipeline.draft_render(d, pipeline.clip_dir(d, m["id"]))
            hist["urls"].append(v["url"])
            jobs.append(d)
        except SystemExit as ex:
            log(f"skipping {v['url']}: {ex}")
    return jobs


HOOKS = ["Wait for it… 😳", "Nobody was ready for this 😭", "He did NOT see that coming 💀", "This went wrong FAST 😭",
         "Watch his reaction 💀"]
TITLES = ["{ch} Wasn't Ready For This 😭", "{ch} Did NOT See That Coming 💀", "{ch} Can't Believe What Just Happened 😂",
          "Chat Lost It When {ch} Did This 😭"]


def _chat_phrase(lines: list[str]) -> str | None:
    """Most repeated short chat phrase at the moment (the audience's own words make the best hooks)."""
    from collections import Counter
    import re as _re
    norm = [l.strip().lower() for l in lines if 1 <= len(l.split()) <= 4 and not l.startswith(":")
            and _re.search(r"[a-z]{2,}", l.lower()) and "@" not in l]
    norm = [n for n in norm if n not in ("lol", "lmao", "lmaooo", "w", "l", "bro")]
    if not norm:
        return None
    top, cnt = Counter(norm).most_common(1)[0]
    return top if cnt >= 2 or len(norm) < 6 else norm[0]


def auto_copy(job: Path, d: Path, platforms: list[str]) -> dict:
    """Agent-less fallback copy. An agent writes far better hooks — prefer running the scheduled-task prompt."""
    from . import hooks
    j = read_json(job / "job.json")
    ch = (j.get("channel") or "He").split()[0]
    ctx = hooks.context(job, d)
    phrase = _chat_phrase(ctx.get("chat_at_this_moment", []))
    hook = f'Chat said "{phrase}" 💀' if phrase else random.choice(HOOKS)
    if hooks.score(hook)["score"] < 70:
        hook = random.choice(HOOKS)
    title = random.choice(TITLES).format(ch=ch)
    post = posts.skeleton(d, j, platforms)
    clean = re.sub(r"[*]", "", hook)
    post.update(hooks=[hook], hook=hook, title_on_video="")
    tags = "#GTA6 #gaming #ViceCity"
    q = random.choice(["Would you have done better? 😭", "Rate this 1-10 👇", "What would you do here? 👀"])
    for p in platforms:
        if p == "youtube":
            post["platforms"][p] = {"title": title[:60], "description": f"{clean}\n{post['credit']}\n{q}\n#Shorts #GTA6",
                                    "tags": ["gta 6", "gta vi", ch.lower(), "gaming"]}
        elif p == "x":
            post["platforms"][p] = {"text": f"{clean} {post['credit']} #GTA6"[:270]}
        else:
            post["platforms"][p] = {"caption": f"{clean}\n{post['credit']}\n{q}\n{tags}"}
    write_json(d / "post.json", post)
    pipeline.render_clip(job, d, hook=hook, hook_secs=0, music="auto")
    return post


def run_daily(minutes: float | None = None, skip_live: bool = False, skip_videos: bool = False,
              do_auto_copy: bool = False, basis: str = "transformative", clips: int | None = None) -> dict:
    cfg = dict(load_config()["daily"])
    if clips:
        cfg["clips_per_source"] = max(1, clips)
    minutes = minutes or cfg["live_minutes"]
    hist = _history()
    report = {"date": dt.datetime.now().isoformat(timespec="minutes"), "live_streams": [], "videos": [], "drafts": []}
    jobs: list[Path] = []
    vid_thread = None
    vid_jobs: list[Path] = []
    if not skip_videos:   # videos are processed while live recording runs
        vid_thread = threading.Thread(target=lambda: vid_jobs.extend(run_videos(cfg, basis, hist)), daemon=True)
        vid_thread.start()
    if not skip_live:
        urls = live_targets(cfg)
        report["live_streams"] = urls
        if urls:
            log(f"recording {len(urls)} live stream(s) for {minutes} min: {urls}")
            jobs += run_live(urls, minutes, basis)
        else:
            log("nobody suitable is live right now")
    if vid_thread:
        vid_thread.join()
        jobs += vid_jobs
        report["videos"] = [read_json(j / "job.json")["webpage_url"] for j in vid_jobs]
    write_json(workspace() / "history.json", hist)
    for job in jobs:
        for d in sorted((job / "clips").glob("*")) if (job / "clips").exists() else []:
            if not (d / "final.mp4").exists():
                continue
            w = read_json(d / "words.json", {}) or {}
            row = {"job": job.name, "clip": int(d.name), "video": str(d / "final.mp4"),
                   "source": read_json(job / "job.json").get("webpage_url"), "transcript": w.get("text", "")[:400]}
            if do_auto_copy:
                auto_copy(job, d, cfg["platforms"])
                chk = posts.check(d, read_json(job / "job.json"), cfg["platforms"])
                row["check"] = chk["ok"]
                if chk["ok"]:
                    row["queued"] = [i["id"] for i in publish.enqueue(d, cfg["platforms"])]
            report["drafts"].append(row)
    out = workspace() / "daily" / f"{dt.date.today().isoformat()}.json"
    write_json(out, report)
    report["report_file"] = str(out)
    return report
