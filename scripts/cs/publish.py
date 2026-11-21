"""Queue, schedule and publish — 100% free, no API keys.

Fetching never needs an account. Posting goes to YOUR accounts through your own browser session:
  `clipstudio login youtube|tiktok|instagram|x` once (you sign in yourself in the ClipStudio browser profile),
  then `publish` uploads due items via YouTube Studio / TikTok Studio / Instagram web / X (browser_post.py).
  Anything else (or a failed upload) -> a ready-to-post folder in ~/ClipStudio/outbox (video, cover, caption.txt).
Scheduling = the queue: each item has a time slot; `publish` posts the ones that are due, so run it from your
daily scheduled task or cron. Safety: items need `approve` unless `post.auto_post = true` in config.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from .util import die, load_config, log, read_json, run, workspace, write_json, ytdlp_base



def qpath() -> Path:
    return workspace() / "queue.json"


def load_q() -> list[dict]:
    return read_json(qpath(), []) or []


def save_q(q: list[dict]):
    write_json(qpath(), q)


# ------------------------------------------------------------------ scheduling
def _tz() -> ZoneInfo:
    return ZoneInfo(load_config()["post"].get("timezone") or "UTC")


def next_slot(platform: str, q: list[dict], after: dt.datetime | None = None) -> dt.datetime:
    cfg = load_config()
    tz = _tz()
    slots = cfg["schedule"].get(platform) or ["12:00", "18:00"]
    taken = {i["scheduled_at"] for i in q if i["platform"] == platform and i["status"] != "failed"}
    now = after or dt.datetime.now(tz) + dt.timedelta(minutes=20)
    for day in range(0, 60):
        d = (now + dt.timedelta(days=day)).date()
        for s in slots:
            hh, mm = map(int, s.split(":"))
            t = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
            if t > now and t.isoformat() not in taken:
                return t
    return now


def enqueue(clip_dir: Path, platforms: list[str], at: str | None = None, account: str | None = None) -> list[dict]:
    post = read_json(clip_dir / "post.json") or die("post.json missing")
    chk = read_json(clip_dir / "check.json")
    if not chk or not chk.get("ok"):
        die("clip has not passed `check` — fix the issues first (or run check)")
    cfg = load_config()
    q = load_q()
    added = []
    for p in platforms:
        when = dt.datetime.fromisoformat(at).astimezone(_tz()) if at else next_slot(p, q)
        item = {
            "id": uuid.uuid4().hex[:8], "clip": str(clip_dir), "video": str(clip_dir / "final.mp4"),
            "cover": str(clip_dir / "cover.jpg") if (clip_dir / "cover.jpg").exists() else None,
            "platform": p, "account": account, "scheduled_at": when.isoformat(),
            "copy": post["platforms"].get(p, {}),
            "status": "approved" if cfg["post"].get("auto_post") else "needs_approval",
            "created": dt.datetime.now(_tz()).isoformat(),
        }
        q.append(item)
        added.append(item)
    save_q(q)
    return added


def approve(ids: list[str]) -> int:
    q = load_q()
    n = 0
    for i in q:
        if i["status"] == "needs_approval" and ("all" in ids or i["id"] in ids):
            i["status"] = "approved"
            n += 1
    save_q(q)
    return n


def export_item(item: dict) -> str:
    d = workspace() / "outbox" / f"{item['platform']}-{item['id']}"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(item["video"], d / "video.mp4")
    if item.get("cover"):
        shutil.copy(item["cover"], d / "cover.jpg")
    c = item["copy"]
    (d / "caption.txt").write_text("\n\n".join(x for x in [c.get("title", ""), c.get("caption") or c.get("text") or
                                                           c.get("description", "")] if x), encoding="utf-8")
    return str(d)


# ------------------------------------------------------------------ runner
def publish(due_only: bool = True, item_ids: list[str] | None = None, dry: bool = False,
            headless: bool | None = None) -> list[dict]:
    from . import browser_post
    cfg = load_config()["post"]
    headless = cfg.get("headless", False) if headless is None else headless
    q = load_q()
    now = dt.datetime.now(_tz())
    done = []
    for i in q:
        if item_ids and i["id"] not in item_ids:
            continue
        if i["status"] != "approved":
            continue
        if due_only and dt.datetime.fromisoformat(i["scheduled_at"]) > now:
            continue
        if dry:
            done.append({**i, "would": "post via browser" if i["platform"] in browser_post.FLOWS else "export"})
            continue
        try:
            if i["platform"] in browser_post.FLOWS and i["platform"] not in cfg.get("export_only", []):
                url = browser_post.post(i, headless=headless)
                i.update(status="posted", url=url)
            else:
                i.update(status="exported", url="exported: " + export_item(i))
            i["posted_at"] = now.isoformat()
            _score_log(i)
        except Exception as ex:  # noqa: BLE001  (never lose the clip: export it and report)
            i.update(status="failed", error=str(ex)[:600], url="exported: " + export_item(i))
        done.append(i)
        save_q(q)
    return done


def _score_log(i: dict):
    p = workspace() / "scoreboard.csv"
    new = not p.exists()
    with open(p, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["posted_at", "platform", "id", "url", "clip", "hook", "views", "checked_at"])
        hook = (read_json(Path(i["clip"]) / "post.json") or {}).get("hook", "")
        w.writerow([i.get("posted_at"), i["platform"], i["id"], i.get("url"), i["clip"], hook, "", ""])


def refresh_stats() -> list[dict]:
    """Learning loop: pull public view counts (no login) for posted YouTube clips."""
    p = workspace() / "scoreboard.csv"
    if not p.exists():
        return []
    rows = list(csv.DictReader(open(p)))
    for r in rows:
        if r["platform"] == "youtube" and r["url"].startswith("http"):
            out = run(ytdlp_base() + ["-j", "--skip-download", r["url"]], check=False).stdout
            try:
                r["views"] = json.loads(out).get("view_count") or r["views"]
                r["checked_at"] = dt.datetime.now().isoformat(timespec="minutes")
            except json.JSONDecodeError:
                pass
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows
