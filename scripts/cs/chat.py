"""Chat, read anonymously.

- Twitch live: IRC as `justinfanNNNN` (Twitch's built-in anonymous login, no account, no token).
- Twitch VOD replay: public GQL with Twitch's web client id (may be blocked for some VODs; we degrade).
- YouTube replay + live: yt-dlp's `live_chat` track (no cookies).
"""
from __future__ import annotations

import json
import random
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import requests

from .util import TWITCH_CLIENT_ID, UA, log, read_json, run, ytdlp_base

HYPE = re.compile(
    r"\b(pog\w*|kekw|lul\w*|lmao+|lmfao|omg+|wtf+|holy|no way|clip (it|that)|clipped|insane|crazy|"
    r"w+|l+|goat|sheesh|bro+|ayo+|what+|nah+|💀|😂|🔥|monkas|omegalul|pepelaugh|ezclap|gg|"
    r"jajaja+|kkkk+|xd+)\b", re.I)


def hype_score(text: str) -> float:
    s = len(HYPE.findall(text or ""))
    if text and text.isupper() and len(text) > 3:
        s += 1
    return min(s, 3)


def _write_jsonl(rows: list[dict], out: Path):
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load(job: Path) -> list[dict]:
    p = job / "chat.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ----------------------------------------------------------------- YouTube
def _parse_yt_line(line: str) -> dict | None:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    rep = d.get("replayChatItemAction") or {}
    off = rep.get("videoOffsetTimeMsec")
    acts = rep.get("actions") or d.get("actions") or []
    for a in acts:
        item = (a.get("addChatItemAction") or {}).get("item") or {}
        r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not r:
            continue
        txt = "".join(x.get("text") or (x.get("emoji", {}).get("shortcuts") or [""])[0] for x in
                      r.get("message", {}).get("runs", []))
        t = float(off) / 1000 if off is not None else int(r.get("timestampUsec", 0)) / 1e6
        return {"t": t, "user": (r.get("authorName") or {}).get("simpleText", ""), "text": txt,
                "paid": "liveChatPaidMessageRenderer" in item}
    return None


def youtube_replay(job: Path) -> int:
    j = read_json(job / "job.json")
    run(ytdlp_base() + ["--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o",
                        str(job / "ytchat"), j["url"]], check=False)
    files = list(job.glob("ytchat*.live_chat.json"))
    if not files:
        log("no YouTube chat replay available for this video")
        return 0
    rows = [r for r in (_parse_yt_line(l) for l in files[0].read_text(encoding="utf-8").splitlines()) if r]
    rows.sort(key=lambda r: r["t"])
    _write_jsonl(rows, job / "chat.jsonl")
    files[0].unlink(missing_ok=True)
    return len(rows)


def _yt_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/live/|/shorts/)([\w-]{11})", url)
    return m.group(1) if m else None


def youtube_live_tail(url: str, out_dir: Path, on_msg, stop: threading.Event):
    """Poll YouTube's own live-chat endpoint anonymously, in 'Live chat' (ALL messages) mode.
    (yt-dlp's reader follows 'Top chat', which hides most messages, and stalls on long streams.)"""
    vid = _yt_video_id(url)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    s.cookies.set("CONSENT", "YES+1", domain=".youtube.com")
    t0 = time.time()
    while not stop.is_set():
        try:
            r = s.get(f"https://www.youtube.com/live_chat?is_popout=1&v={vid}", timeout=20)
            m = re.search(r'(?:window\["ytInitialData"\]|var ytInitialData)\s*=\s*(\{.+?\});\s*</script>', r.text, re.S)
            data = json.loads(m.group(1))
            key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', r.text).group(1)
            ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', r.text).group(1)
            lc = data["contents"]["liveChatRenderer"]
            try:
                items = lc["header"]["liveChatHeaderRenderer"]["viewSelector"]["sortFilterSubMenuRenderer"]["subMenuItems"]
                cont = items[-1]["continuation"]["reloadContinuationData"]["continuation"]
            except (KeyError, IndexError):
                cont = lc["continuations"][0]["invalidationContinuationData"]["continuation"]
            while not stop.is_set():
                j = s.post(f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={key}",
                           json={"context": {"client": {"clientName": "WEB", "clientVersion": ver}},
                                 "continuation": cont}, timeout=20).json()
                lcc = j["continuationContents"]["liveChatContinuation"]
                for a in lcc.get("actions", []):
                    item = (a.get("addChatItemAction") or {}).get("item") or {}
                    rr = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
                    if rr:
                        txt = "".join(x.get("text") or (x.get("emoji", {}).get("shortcuts") or [""])[0]
                                      for x in rr.get("message", {}).get("runs", []))
                        on_msg(time.time() - t0, (rr.get("authorName") or {}).get("simpleText", ""), txt)
                c = lcc["continuations"][0]
                cd = c.get("invalidationContinuationData") or c.get("timedContinuationData") or \
                    c.get("reloadContinuationData")
                cont = cd["continuation"]
                stop.wait(min(cd.get("timeoutMs", 3000), 4000) / 1000)
        except Exception as ex:  # noqa: BLE001
            log(f"youtube chat reconnect ({str(ex)[:80]})")
            stop.wait(5)


# ----------------------------------------------------------------- Twitch
def twitch_vod_id(url: str) -> str | None:
    m = re.search(r"twitch\.tv/(?:\w+/)?videos?/(\d+)", url)
    return m.group(1) if m else None


def twitch_replay(job: Path, max_pages: int = 4000) -> int:
    j = read_json(job / "job.json")
    vid = twitch_vod_id(j["url"])
    if not vid:
        log("not a Twitch VOD url; skipping chat replay")
        return 0
    s = requests.Session()
    s.headers.update({"Client-ID": TWITCH_CLIENT_ID, "User-Agent": UA})
    persisted = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
    rows, cursor, pages = [], None, 0
    while pages < max_pages:
        var = {"videoID": vid, "cursor": cursor} if cursor else {"videoID": vid, "contentOffsetSeconds": 0}
        body = [{"operationName": "VideoCommentsByOffsetOrCursor", "variables": var,
                 "extensions": {"persistedQuery": {"version": 1, "sha256Hash": persisted}}}]
        try:
            r = s.post("https://gql.twitch.tv/gql", json=body, timeout=20).json()
            com = r[0]["data"]["video"]["comments"]
        except Exception:  # noqa: BLE001
            if pages == 0:
                log("Twitch VOD chat replay is not available anonymously for this VOD "
                    "(Twitch integrity check). Scoring will use audio + speech instead.")
            break
        for e in com.get("edges", []):
            n = e["node"]
            txt = "".join(fr.get("text", "") for fr in (n.get("message") or {}).get("fragments", []))
            rows.append({"t": float(n.get("contentOffsetSeconds", 0)),
                         "user": ((n.get("commenter") or {}).get("displayName") or ""), "text": txt})
        if not com.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = com["edges"][-1]["cursor"]
        pages += 1
        time.sleep(0.05)
    if rows:
        rows.sort(key=lambda r: r["t"])
        _write_jsonl(rows, job / "chat.jsonl")
    return len(rows)


def twitch_irc(login: str, on_msg, stop: threading.Event):
    """Anonymous Twitch IRC: no account, no OAuth token."""
    nick = f"justinfan{random.randint(10000, 99999)}"
    t0 = time.time()
    while not stop.is_set():
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=15)
            s.sendall(f"NICK {nick}\r\nJOIN #{login.lower()}\r\n".encode())
            s.settimeout(1.0)
            buf = b""
            while not stop.is_set():
                try:
                    data = s.recv(8192)
                    if not data:
                        break
                    buf += data
                except socket.timeout:
                    continue
                *lines, buf = buf.split(b"\r\n")
                for raw in lines:
                    line = raw.decode("utf-8", "ignore")
                    if line.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                    elif " PRIVMSG " in line:
                        user = line[1:line.find("!")]
                        text = line.split(" PRIVMSG ", 1)[1].split(" :", 1)[-1]
                        on_msg(time.time() - t0, user, text)
        except OSError as ex:
            log(f"chat reconnect ({ex})")
            time.sleep(3)


def fetch_replay(job: Path) -> int:
    j = read_json(job / "job.json")
    if j["platform"] == "youtube":
        return youtube_replay(job)
    if j["platform"] == "twitch":
        return twitch_replay(job)
    return 0
