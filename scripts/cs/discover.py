"""Discovery: who is live right now, and what is trending — no accounts, no API keys."""
from __future__ import annotations

import json
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

from .util import TWITCH_CLIENT_ID, UA, log, run, ytdlp_base

GAME_ALIASES = {
    "gta 6": "Grand Theft Auto VI", "gta6": "Grand Theft Auto VI", "gta vi": "Grand Theft Auto VI",
    "gta 5": "Grand Theft Auto V", "gta v": "Grand Theft Auto V",
}

YT_SP_UPLOAD_DATE = "CAI%3D"      # sort by upload date
YT_SP_LIVE_NOW = "EgJAAQ%3D%3D"   # live right now
YT_SP_TODAY = "EgIIAg%3D%3D"      # uploaded today


def twitch_gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post("https://gql.twitch.tv/gql", json={"query": query, "variables": variables or {}},
                      headers={"Client-ID": TWITCH_CLIENT_ID, "User-Agent": UA}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def twitch_live(game: str = "gta 6", limit: int = 20, language: str | None = None) -> list[dict]:
    name = GAME_ALIASES.get(game.lower().strip(), game)
    q = """query($name:String!,$n:Int!){ game(name:$name){ id name viewersCount
            streams(first:$n){ edges{ node{ id title viewersCount createdAt language
              broadcaster{ login displayName } } } } } }"""
    d = twitch_gql(q, {"name": name, "n": min(limit * 2, 100)})
    if not d.get("game"):
        return []
    out = []
    for e in d["game"]["streams"]["edges"]:
        n = e["node"]
        if language and (n.get("language") or "").lower() != language.lower():
            continue
        login = n["broadcaster"]["login"]
        out.append({
            "platform": "twitch", "channel": n["broadcaster"]["displayName"], "login": login,
            "url": f"https://www.twitch.tv/{login}", "title": n["title"], "viewers": n["viewersCount"],
            "started": n["createdAt"], "language": n.get("language"),
        })
    return sorted(out, key=lambda x: -x["viewers"])[:limit]


def twitch_channel(login: str) -> dict:
    q = """query($l:String!){ user(login:$l){ displayName description
            stream{ id title viewersCount createdAt game{name} } } }"""
    d = twitch_gql(q, {"l": login.lower()})
    return d.get("user") or {}


def _yt_search(query: str, sp: str, limit: int) -> list[dict]:
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp={sp}"
    r = run(ytdlp_base() + ["--flat-playlist", "-J", "--playlist-end", str(limit), url], check=False)
    try:
        return json.loads(r.stdout).get("entries", []) or []
    except json.JSONDecodeError:
        log(r.stderr[-500:])
        return []


def youtube_live(query: str = "GTA 6", limit: int = 20) -> list[dict]:
    out = []
    for e in _yt_search(query + " live", YT_SP_LIVE_NOW, limit):
        out.append({
            "platform": "youtube", "channel": e.get("channel") or e.get("uploader"), "url": e.get("url"),
            "title": e.get("title"), "viewers": e.get("concurrent_view_count") or e.get("view_count"),
            "id": e.get("id"),
        })
    return out


def streams(game: str = "gta 6", limit: int = 15, language: str | None = None) -> list[dict]:
    """Merged list of live streams across Twitch + YouTube, ranked by viewers."""
    rows = []
    try:
        rows += twitch_live(game, limit, language)
    except Exception as ex:  # noqa: BLE001
        log(f"twitch lookup failed: {ex}")
    try:
        rows += youtube_live(game, limit)
    except Exception as ex:  # noqa: BLE001
        log(f"youtube lookup failed: {ex}")
    return sorted(rows, key=lambda x: -(x.get("viewers") or 0))[: limit * 2]


def _details(url: str) -> dict | None:
    r = run(ytdlp_base() + ["-j", "--skip-download", url], check=False)
    try:
        return json.loads(r.stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return None


def trends(query: str = "GTA 6", hours: int = 24, limit: int = 15, scan: int = 40) -> list[dict]:
    """YouTube uploads from the last `hours`, ranked by views per hour (what is blowing up right now)."""
    entries = _yt_search(query, YT_SP_UPLOAD_DATE, scan)
    urls = [e["url"] for e in entries if e.get("url")]
    with ThreadPoolExecutor(8) as ex:
        infos = [i for i in ex.map(_details, urls) if i]
    now = time.time()
    out = []
    for i in infos:
        ts = i.get("timestamp") or 0
        age_h = max((now - ts) / 3600, 0.25) if ts else None
        if age_h is None or age_h > hours:
            continue
        views = i.get("view_count") or 0
        out.append({
            "platform": "youtube", "url": i.get("webpage_url"), "title": i.get("title"), "channel": i.get("channel"),
            "views": views, "age_hours": round(age_h, 1), "views_per_hour": int(views / age_h),
            "duration": i.get("duration"), "is_short": (i.get("duration") or 999) <= 180,
            "was_live": i.get("live_status") in ("was_live", "is_live"),
        })
    return sorted(out, key=lambda x: -x["views_per_hour"])[:limit]


def vods(channel_url: str, limit: int = 10) -> list[dict]:
    """Recent recorded streams/VODs of a channel (YouTube /streams tab or Twitch archives)."""
    u = channel_url.rstrip("/")
    if "youtube.com" in u and not u.endswith(("/streams", "/videos")):
        u += "/streams"
    if "twitch.tv" in u and "/videos" not in u:
        u += "/videos?filter=archives&sort=time"
    r = run(ytdlp_base() + ["--flat-playlist", "-J", "--playlist-end", str(limit), u], check=False)
    try:
        ents = json.loads(r.stdout).get("entries", []) or []
    except json.JSONDecodeError:
        ents = []
    rows = [{"url": e.get("url"), "title": e.get("title"), "duration": e.get("duration"),
             "views": e.get("view_count")} for e in ents]
    if not rows and "twitch.tv" in u:
        log("Twitch did not list archives anonymously for this channel (VODs may be disabled or sub-only). "
            "Paste a https://www.twitch.tv/videos/<id> URL directly instead.")
    return rows


def yt_filter(sort: str = "views", duration: str | None = None, days: int | None = None) -> str:
    """Build YouTube's `sp` search filter (protobuf -> base64): sort x upload date x duration."""
    import base64
    inner = b""
    if days:
        upload = 2 if days <= 1 else 3 if days <= 7 else 4 if days <= 31 else 5   # today/week/month/year
        inner += bytes([0x08, upload])
    if duration:
        inner += bytes([0x18, {"short": 1, "long": 2, "medium": 3}[duration]])
    raw = bytes([0x08, {"relevance": 0, "date": 2, "views": 3}[sort]])
    if inner:
        raw += bytes([0x12, len(inner)]) + inner
    return urllib.parse.quote(base64.b64encode(raw).decode())


def videos(query: str = "GTA 6 gameplay", min_minutes: float = 3, max_minutes: float = 600, sort: str = "views",
           limit: int = 15, days: int | None = 30) -> list[dict]:
    """Any YouTube video worth clipping — gameplay, walkthroughs, funny moments, reactions, viral videos —
    filtered by length and recency. Not just streams."""
    buckets = []
    if min_minutes < 4:
        buckets.append("short")
    if max_minutes > 4 and min_minutes < 20:
        buckets.append("medium")
    if max_minutes > 20:
        buckets.append("long")
    rows, seen = [], set()
    for b in buckets:
        for e in _yt_search(query, yt_filter(sort, b, days), limit * 2):
            d = e.get("duration") or 0
            if not e.get("url") or e["id"] in seen or not (min_minutes * 60 <= d <= max_minutes * 60):
                continue
            seen.add(e["id"])
            rows.append({"platform": "youtube", "url": e["url"], "title": e.get("title"), "channel": e.get("channel"),
                         "views": e.get("view_count"), "minutes": round(d / 60, 1),
                         "was_live": e.get("live_status") == "was_live"})
    key = (lambda r: -(r["views"] or 0)) if sort == "views" else (lambda r: 0)
    return sorted(rows, key=key)[:limit]
