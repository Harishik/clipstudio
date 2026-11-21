"""Anonymous Twitch VOD resolver.

Twitch hides VOD *metadata* from anonymous API calls, so yt-dlp/streamlink often fail with
"video does not exist". But the *playback* token is still public (it's what the embed player uses),
so we resolve the HLS playlists ourselves: no account, no OAuth, no cookies.
"""
from __future__ import annotations

import re

import requests

from .util import TWITCH_CLIENT_ID, UA, die

TOKEN_HASH = "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9"


def vod_id(url: str) -> str | None:
    m = re.search(r"twitch\.tv/(?:[\w-]+/)?videos?/(\d+)", url)
    return m.group(1) if m else None


def _token(vid: str) -> dict:
    body = [{"operationName": "PlaybackAccessToken",
             "variables": {"isLive": False, "login": "", "isVod": True, "vodID": vid, "playerType": "embed",
                           "platform": "web"},
             "extensions": {"persistedQuery": {"version": 1, "sha256Hash": TOKEN_HASH}}}]
    r = requests.post("https://gql.twitch.tv/gql", json=body, headers={"Client-ID": TWITCH_CLIENT_ID,
                                                                         "User-Agent": UA}, timeout=20)
    tok = r.json()[0]["data"]["videoPlaybackAccessToken"]
    if not tok:
        die(f"Twitch VOD {vid} not found (deleted, expired, or sub-only)")
    return tok


def variants(vid: str) -> list[dict]:
    t = _token(vid)
    r = requests.get(f"https://usher.ttvnw.net/vod/{vid}.m3u8",
                     params={"sig": t["signature"], "token": t["value"], "allow_source": "true",
                             "allow_audio_only": "true", "player": "twitchweb", "playlist_include_framerate": "true"},
                     headers={"User-Agent": UA}, timeout=20)
    if r.status_code != 200:
        die(f"Twitch usher refused VOD {vid} ({r.status_code}): {r.text[:200]}")
    out, inf = [], None
    for line in r.text.splitlines():
        if line.startswith("#EXT-X-STREAM-INF"):
            inf = line
        elif line.startswith("http") and inf:
            res = re.search(r"RESOLUTION=(\d+)x(\d+)", inf)
            out.append({"url": line, "height": int(res.group(2)) if res else 0,
                        "audio_only": "audio_only" in line or 'VIDEO="audio_only"' in inf,
                        "bandwidth": int(re.search(r"BANDWIDTH=(\d+)", inf).group(1))})
            inf = None
    if not out:
        die(f"no playable variants for VOD {vid}")
    return out


def check_access(url: str):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    if r.status_code == 403 and "country" in r.text.lower():
        die("Twitch blocks VOD playback from your network's country (e.g. South Korea). "
            "Live streams still work; for VODs use a network in another region.")
    if r.status_code != 200:
        die(f"Twitch VOD playlist returned {r.status_code}")
    return r.text


def info(url: str) -> dict:
    vid = vod_id(url)
    vs = variants(vid)
    best = max((v for v in vs if not v["audio_only"]), key=lambda v: v["height"], default=vs[0])
    text = check_access(best["url"])
    dur = sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", text))
    m = re.search(r"/[0-9a-f]+_([a-z0-9_]+?)_\d{6,}_\d{6,}/", best["url"])
    login = m.group(1) if m else None
    return {"title": f"Twitch VOD {vid}" + (f" — {login}" if login else ""),
            "duration": dur, "channel": login, "channel_url": f"https://www.twitch.tv/{login}" if login else None,
            "webpage_url": f"https://www.twitch.tv/videos/{vid}", "live_status": "was_live", "extractor": "twitch-anon"}


def media_urls(url: str, max_height: int = 1080, audio_only: bool = False) -> str:
    vs = variants(vod_id(url))
    if audio_only:
        a = [v for v in vs if v["audio_only"]]
        if a:
            return a[0]["url"]
    vids = [v for v in vs if not v["audio_only"]]
    ok = [v for v in vids if v["height"] <= max_height] or vids
    return max(ok, key=lambda v: (v["height"], v["bandwidth"]))["url"]
