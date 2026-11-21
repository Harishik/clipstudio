"""Shared helpers: paths, config, subprocess, job folders."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

SKILL_ROOT = Path(__file__).resolve().parents[2]
ASSETS = SKILL_ROOT / "assets"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch's public web client id (no login)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


# ---------------------------------------------------------------- config
def config_path() -> Path:
    env = os.environ.get("CLIPSTUDIO_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".clipstudio" / "config.toml"


DEFAULTS = {
    "workspace": "~/ClipStudio",
    "language": "auto",
    "whisper_model": "small",
    "font": "",
    "music_dir": "",
    "music_volume_db": -22,
    "brand": {"handle": "", "watermark": ""},
    "render": {"layout": "auto", "caption_style": "auto", "max_words_per_line": 0, "caption_size": 0, "accent": "#FFE600"},
    "post": {"platforms": ["youtube"], "auto_post": False, "timezone": "UTC", "headless": False, "export_only": []},
    "schedule": {
        "youtube": ["12:00", "17:00", "20:00"],
        "tiktok": ["11:00", "19:00", "21:00"],
        "instagram": ["11:00", "18:00"],
        "x": ["09:00", "13:00", "18:00"],
        "facebook": ["13:00"],
    },
    "daily": {"game": "gta 6", "channels": [], "video_query": "GTA 6", "live_minutes": 60, "max_streams": 2,
              "videos_per_day": 2, "clips_per_source": 3, "platforms": ["youtube", "tiktok", "instagram"],
              "min_viewers": 500, "lang": ""},
}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config() -> dict:
    p = config_path()
    cfg = DEFAULTS
    if p.exists() and tomllib:
        with open(p, "rb") as f:
            cfg = _merge(DEFAULTS, tomllib.load(f))
    return cfg


def workspace() -> Path:
    ws = Path(os.environ.get("CLIPSTUDIO_WORKSPACE") or load_config()["workspace"]).expanduser()
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ---------------------------------------------------------------- jobs
def slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-").lower()
    return s[:n] or "job"


def job_dir(job_id: str) -> Path:
    p = Path(job_id)
    if p.is_dir():
        return p
    d = workspace() / "jobs" / job_id
    if not d.exists():
        die(f"job not found: {job_id} (looked in {d})")
    return d


def new_job(name: str) -> Path:
    jid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug(name, 30)
    d = workspace() / "jobs" / jid
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(p: Path, default=None):
    p = Path(p)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(p: Path, data) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(p)
    return p


# ---------------------------------------------------------------- processes
def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def run(cmd: list[str], check: bool = True, capture: bool = True, **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=capture, text=True, **kw)
    if check and r.returncode != 0:
        tail = (r.stderr or "")[-1500:]
        die(f"command failed ({r.returncode}): {' '.join(map(str, cmd[:6]))} ...\n{tail}")
    return r


def ytdlp_base() -> list[str]:
    """yt-dlp invocation. Never passes cookies: everything here is anonymous."""
    exe = shutil.which("yt-dlp")
    cmd = [exe] if exe else [sys.executable, "-m", "yt_dlp"]
    cmd += ["--no-warnings", "--no-playlist"]
    if not have("deno") and have("node"):
        cmd += ["--js-runtimes", "node"]
    if have("node") or have("deno"):
        cmd += ["--remote-components", "ejs:github"]   # free YouTube challenge solver -> all formats available
    return cmd


def streamlink_base() -> list[str]:
    exe = shutil.which("streamlink")
    return [exe] if exe else [sys.executable, "-m", "streamlink"]


def ffprobe_duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], check=False)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def ffprobe_size(path: Path) -> tuple[int, int]:
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(path)])
    w, h = r.stdout.strip().split("\n")[0].split(",")[:2]
    return int(w), int(h)


def hms(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_time(s: str | float | int) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if re.fullmatch(r"[\d.]+", s):
        return float(s)
    parts = [float(x) for x in s.split(":")]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


def platform_of(url: str) -> str:
    u = url.lower()
    if "twitch.tv" in u:
        return "twitch"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if os.path.exists(url):
        return "local"
    return "other"


def font_path(bold: bool = True) -> str:
    cfg_font = load_config().get("font")
    if cfg_font and Path(cfg_font).expanduser().exists():
        return str(Path(cfg_font).expanduser())
    f = ASSETS / "fonts" / "Anton-Regular.ttf"
    if f.exists():
        return str(f)
    for cand in ["/System/Library/Fonts/Supplemental/Impact.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "C:/Windows/Fonts/impact.ttf"]:
        if Path(cand).exists():
            return cand
    die("no font found; set `font = \"/path/to/font.ttf\"` in config")


UNICODE_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", "C:/Windows/Fonts/Nirmala.ttf",
    "C:/Windows/Fonts/arialuni.ttf",
]


def is_latin(text: str) -> bool:
    return all(ord(c) < 0x250 or c in "’‘“”…–—•🎥" or 0x2000 <= ord(c) <= 0x206F for c in text)


def font_for(text: str, display: bool = True) -> str:
    """Bundled display font for Latin text; a system Unicode font for Hindi, Cyrillic, Arabic, CJK..."""
    if is_latin(text):
        return font_path() if display else body_font_path()
    for c in [load_config().get("unicode_font", "")] + UNICODE_FONTS:
        if c and Path(c).expanduser().exists():
            return str(Path(c).expanduser())
    log("no Unicode font found for non-Latin captions; set `unicode_font` in config")
    return font_path()


def body_font_path() -> str:
    f = ASSETS / "fonts" / "Montserrat-Variable.ttf"
    return str(f) if f.exists() else font_path()


def print_json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))
