"""Per-platform post copy: specs, skeletons for the agent to fill, and rule checks before anything posts."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .util import ffprobe_duration, ffprobe_size, read_json, write_json

PLATFORMS = {
    "youtube": {
        "label": "YouTube Shorts", "max_secs": 180, "title_max": 100, "desc_max": 5000, "tags_chars_max": 500,
        "hashtags": (2, 4), "must": ["#Shorts"],
        "style": "Title = the hook as a curiosity gap, <=60 chars ideal, 1 emoji max. Description: 1-2 lines of "
                 "context + credit line + 3 hashtags. Tags: game, streamer, moment keywords.",
    },
    "tiktok": {
        "label": "TikTok", "max_secs": 600, "caption_max": 2200, "hashtags": (3, 5),
        "style": "Lowercase-casual, first line is the hook, end with a question to drive comments. "
                 "Hashtags: 1 broad (#gaming), 2 niche (#gta6 #vicecity), 1 streamer tag.",
    },
    "instagram": {
        "label": "Instagram Reels", "max_secs": 180, "caption_max": 2200, "hashtags": (3, 5),
        "style": "Hook line, one line of context, credit, CTA (follow/save/share). 3-5 hashtags at the end.",
    },
    "facebook": {
        "label": "Facebook Reels", "max_secs": 90, "caption_max": 2200, "hashtags": (2, 3),
        "style": "Plain-language description of the moment (older audience), 2-3 hashtags.",
    },
    "x": {
        "label": "X / Twitter", "max_secs": 140, "caption_max": 280, "hashtags": (1, 2),
        "style": "Punchy one-liner reaction + credit handle. Under 240 chars to leave room.",
    },
}

# Hard rules: never post these (platform strikes, misinformation, piracy, or impersonation).
BANNED = [
    r"\bleak(ed|s)?\b", r"free download", r"play (it )?early", r"\bpc (download|crack)\b", r"\bcrack(ed)?\b",
    r"money (glitch|drop|hack)", r"mod ?menu", r"afk (bot|farm)", r"\bofficial rockstar\b", r"we are rockstar",
    r"giveaway.*(dm|link in bio)", r"\bfree v-?bucks\b", r"shark card (generator|hack)",
]


def hashtags(text: str) -> list[str]:
    return re.findall(r"#\w+", text or "")


def skeleton(clip_dir: Path, job: dict, platforms: list[str]) -> dict:
    from . import hooks
    words = read_json(clip_dir / "words.json", {}) or {}
    credit = credit_line(job)
    try:
        hc = hooks.context(clip_dir.parent.parent, clip_dir)
    except Exception:  # noqa: BLE001
        hc = {}
    post = {
        "_context": {
            "source": job.get("webpage_url"), "channel": job.get("channel"), "basis": job.get("basis"),
            "campaign": job.get("campaign"), "transcript": words.get("text", "")[:1500],
            "audience_reactions": {"chat": hc.get("chat_at_this_moment", [])[:25],
                                   "comments": hc.get("comments_about_this_moment", [])[:8]},
            "post_title_formulas": hc.get("post_title_formulas", []),
            "hook_rules": hc.get("rules", []),
            "instructions": "Write 3 on-screen hooks with different formulas (curiosity / stakes / reaction), pick "
                            "one as `hook`. Then per platform: a title/caption whose FIRST line is the hook idea, "
                            "1 line of context, the credit line, a comment-bait question, 3-5 hashtags. Use the "
                            "audience's own words where they're funny. Check with `clipstudio hookcheck`.",
            "_specs": {p: PLATFORMS[p]["style"] for p in platforms},
        },
        "hooks": ["", "", ""], "hook": "", "title_on_video": "", "credit": credit, "language": words.get("language"),
        "platforms": {},
    }
    for p in platforms:
        if p == "youtube":
            post["platforms"][p] = {"title": "", "description": f"\n\n{credit}\n#Shorts", "tags": []}
        elif p == "x":
            post["platforms"][p] = {"text": ""}
        else:
            post["platforms"][p] = {"caption": ""}
    return post


def credit_line(job: dict) -> str:
    ch = job.get("channel") or ""
    url = job.get("channel_url") or job.get("webpage_url") or ""
    if job.get("platform") == "twitch" and ch:
        return f"🎥 Credit: {ch} (twitch.tv/{ch.lower()})"
    return f"🎥 Credit: {ch} — {url}".strip(" —")


def _lufs(path: Path) -> float | None:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null",
                        "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    try:
        return float(json.loads(m.group(0))["input_i"]) if m else None
    except (ValueError, KeyError):
        return None


def check(clip_dir: Path, job: dict, platforms: list[str] | None = None, rules: dict | None = None) -> dict:
    """Return {'ok': bool, 'issues': [...], 'warnings': [...]} for the rendered clip + its post copy."""
    issues, warns = [], []
    video = clip_dir / "final.mp4"
    post = read_json(clip_dir / "post.json")
    if not video.exists():
        issues.append("final.mp4 missing — render first")
        return {"ok": False, "issues": issues, "warnings": warns}
    w, h = ffprobe_size(video)
    dur = ffprobe_duration(video)
    if (w, h) != (1080, 1920):
        issues.append(f"resolution {w}x{h}, expected 1080x1920")
    lufs = _lufs(video)
    if lufs is not None and not -16.5 <= lufs <= -11.5:
        warns.append(f"loudness {lufs:.1f} LUFS (target -14)")
    if not post:
        issues.append("post.json missing — run `posts` and fill it")
        return {"ok": False, "issues": issues, "warnings": warns, "duration": dur}
    platforms = platforms or list(post.get("platforms", {}))
    rules = rules or {}
    if job.get("basis") == "campaign" and not rules:
        warns.append("basis is 'campaign' but no campaign rules file was given (--rules)")
    all_text = json.dumps(post.get("platforms", {}), ensure_ascii=False) + " " + (post.get("hook") or "")
    for pat in BANNED + [re.escape(b) for b in rules.get("banned_words", [])]:
        if re.search(pat, all_text, re.I):
            issues.append(f"banned content matched: /{pat}/")
    if not post.get("hook"):
        warns.append("no hook chosen")
    else:
        from . import hooks as _h
        sc = _h.score(post["hook"], "hook")
        if sc["score"] < 70:
            warns.append(f"hook scores {sc['score']}/100: " + "; ".join(sc["tips"]))
    for p in platforms:
        spec = PLATFORMS.get(p)
        blk = (post.get("platforms") or {}).get(p)
        if not spec:
            issues.append(f"unknown platform {p}")
            continue
        if not blk:
            issues.append(f"{p}: no post copy")
            continue
        if dur > spec["max_secs"]:
            issues.append(f"{p}: {dur:.0f}s is longer than {spec['max_secs']}s")
        if p == "youtube":
            t = blk.get("title", "")
            from . import hooks as _h
            sc = _h.score(t, "title")
            if sc["score"] < 70:
                warns.append(f"youtube title scores {sc['score']}/100: " + "; ".join(sc["tips"]))
            if not t:
                issues.append("youtube: empty title")
            if len(t) > spec["title_max"]:
                issues.append(f"youtube: title {len(t)}>100 chars")
            if len(blk.get("description", "")) > spec["desc_max"]:
                issues.append("youtube: description too long")
            if len(",".join(blk.get("tags", []))) > spec["tags_chars_max"]:
                issues.append("youtube: tags exceed 500 chars")
            text = t + " " + blk.get("description", "")
        else:
            text = blk.get("caption") or blk.get("text") or ""
            if not text.strip():
                issues.append(f"{p}: empty caption")
            if len(text) > spec["caption_max"]:
                issues.append(f"{p}: caption {len(text)}>{spec['caption_max']} chars")
        tags = hashtags(text)
        lo, hi = spec["hashtags"]
        if len(tags) > hi + 2:
            warns.append(f"{p}: {len(tags)} hashtags (best {lo}-{hi})")
        for must in spec.get("must", []):
            if must.lower() not in text.lower():
                warns.append(f"{p}: missing {must}")
        for req in rules.get("required_hashtags", []):
            if req.lower() not in text.lower():
                issues.append(f"{p}: campaign requires {req}")
        for req in rules.get("required_mentions", []):
            if req.lower() not in text.lower():
                issues.append(f"{p}: campaign requires mention {req}")
        if (rules.get("require_credit", True) and job.get("basis") != "own"
                and (job.get("channel") or "").lower() not in text.lower() and "credit" not in text.lower()):
            issues.append(f"{p}: no credit to the source creator")
    if rules.get("min_secs") and dur < rules["min_secs"]:
        issues.append(f"campaign: {dur:.0f}s < min {rules['min_secs']}s")
    if rules.get("max_secs") and dur > rules["max_secs"]:
        issues.append(f"campaign: {dur:.0f}s > max {rules['max_secs']}s")
    if rules.get("platforms"):
        for p in platforms:
            if p not in rules["platforms"]:
                issues.append(f"campaign does not allow platform {p}")
    res = {"ok": not issues, "issues": issues, "warnings": warns, "duration": round(dur, 1), "lufs": lufs}
    write_json(clip_dir / "check.json", res)
    return res
