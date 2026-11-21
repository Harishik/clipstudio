"""Vertical 1080x1920 editor — "viral" clip-channel style by default.

What a top stream-clip edit does, and what this renders:
  * tight pacing      — dead air (no speech + quiet) is cut out automatically (`tighten`)
  * clean split       — webcam panel on top, gameplay below, no gaps; or gameplay fitted over a blurred copy
                        with the headline above and captions below (nothing covers the action or the face)
  * captions          — 1-2 words at a time, ALL CAPS Montserrat Black with a heavy outline + shadow,
                        active word highlighted, chunk pops in (scale 0.8 -> 1.1 -> 1.0); kept out of the face and
                        out of the bottom/right app UI
  * headline          — short outlined hook; *asterisked* words get the accent colour
  * impact moments    — auto-detected loudness peaks (or --punch) get zoom-in + camera shake + white flash +
                        an impact sound, plus an emoji pop
  * sound             — synthesized whoosh / boom / pop (no licensing issues), optional music ducked under the
                        voice, loudness normalised to -14 LUFS
  * grade             — light contrast/saturation boost + sharpen
Overlays are drawn with Pillow, so any ffmpeg build works (no libass/freetype needed).
"""
from __future__ import annotations

import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import captions as capx
from . import facecam as fc
from .util import (ASSETS, body_font_path, die, ffprobe_duration, ffprobe_size, font_for, is_latin, load_config,
                   log, run)

W, H = 1080, 1920
SAFE_X = 90            # clear of the left edge and the right-side like/comment buttons
CAM_H = 740            # facecam panel height
FPS = 30
BLUR_VID_Y = 640       # top of the fitted gameplay in blur layout (608 px tall)

PALETTE = ["#FFE600", "#3DFF6E"]   # highlight colours, alternated per caption chunk
EMPH = "#FF3B3B"                   # emphasis words (screams, swears, hype)

PROFANITY = re.compile(r"\b(fuck\w*|shit\w*|bitch\w*|cunt|motherfuck\w*|nigg\w*|fag\w*|retard\w*)\b", re.I)
HYPE_WORD = re.compile(r"^(no+|what+|bro+|yo+|oh+|omg|wow+|yes+|run+|go+|dude|insane|crazy|holy)[!?.,]*$", re.I)


# ------------------------------------------------------------------ fonts & text
def _variable(path: str) -> bool:
    return "Variable" in path or "[wght]" in path


def _font(path: str, size: int, weight: int = 900) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, max(8, int(size)))
    if _variable(path):
        try:
            f.set_variation_by_axes([weight])
        except Exception:  # noqa: BLE001
            pass
    return f


def _hex(c: str, a: int = 255) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def caption_font(text: str) -> str:
    cfg = load_config().get("font")
    if cfg and Path(cfg).expanduser().exists() and is_latin(text):
        return str(Path(cfg).expanduser())
    return body_font_path() if is_latin(text) else font_for(text)


def censor(word: str) -> str:
    return PROFANITY.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 2) + m.group(0)[-1], word)


def _outlined(d: ImageDraw.ImageDraw, xy, text, font, fill, stroke, shadow=True):
    x, y = xy
    if shadow:
        d.text((x + stroke * 0.6, y + stroke * 0.9), text, font=font, fill=(0, 0, 0, 150), stroke_width=stroke,
               stroke_fill=(0, 0, 0, 150))
    d.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))


def _rich_lines(text: str, d, path, size, max_w):
    """Split '*word*' emphasis markers, wrap into lines of (word, emphasised)."""
    toks = [(t.strip("*"), t.startswith("*") and t.endswith("*") and len(t) > 2) for t in text.split()]
    f = _font(path, size)
    lines, cur = [], []
    for t in toks:
        trial = " ".join(w for w, _ in cur + [t])
        if cur and d.textlength(trial, font=f) > max_w:
            lines.append(cur)
            cur = [t]
        else:
            cur.append(t)
    if cur:
        lines.append(cur)
    return lines, f


EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F2FF\uFE0F\u200D]+")


def draw_headline(img, text, y_center, *, accent, size=62, max_lines=2, upper=True, scale=1.0, backing=False,
                  color=None, emph_color=None, fontfile=None):
    """Outlined headline (no cheap white box). *word* = accent colour."""
    if not text:
        return
    d = ImageDraw.Draw(img)
    emo = "".join(EMOJI_RE.findall(text))
    text = EMOJI_RE.sub("", text).strip()
    text = text.upper() if (upper and is_latin(text)) else text
    path = fontfile if (fontfile and is_latin(text)) else caption_font(text)
    size = int(size * scale)
    lines, f = _rich_lines(text, d, path, size, W - 2 * SAFE_X)
    while len(lines) > max_lines and size > 36:
        size -= 4
        lines, f = _rich_lines(text, d, path, size, W - 2 * SAFE_X)
    asc, desc = f.getmetrics()
    lh = asc + desc + 2
    y = y_center - lh * len(lines) / 2
    stroke = max(5, size // 9)
    space = d.textlength(" ", font=f)
    if backing:  # soft dark band so white text reads on any background (white shirts, sky...)
        bw = max(sum(d.textlength(w, font=f) for w, _ in ln) + space * (len(ln) - 1) for ln in lines)
        band = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(band).rounded_rectangle([(W - bw) / 2 - 34, y - 14, (W + bw) / 2 + 34 + (90 if emo else 0),
                                                y + lh * len(lines) + 10], radius=26, fill=(0, 0, 0, 150))
        img.alpha_composite(band)
    for line in lines:
        widths = [d.textlength(w, font=f) for w, _ in line]
        x = (W - (sum(widths) + space * (len(line) - 1))) / 2
        for (w, emph), wd in zip(line, widths):
            base_c = color or (255, 255, 255, 255)
            _outlined(d, (x, y), w, f, (emph_color or _hex(accent)) if emph else base_c, stroke)
            x += wd + space
        y += lh
    if emo:
        ei = emoji_img(emo[0], int(size * 1.1))
        if ei:
            img.alpha_composite(ei, (int(min(x + 6, W - ei.width - 10)), int(y - lh + (lh - ei.height) / 2)))


def draw_box_headline(img, text, y_top, *, size=50):
    """Optional classic white box headline (--headline-style box)."""
    d = ImageDraw.Draw(img)
    path = caption_font(text)
    f = _font(path, size, 800)
    words, lines, cur = text.replace("*", "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= W - 2 * SAFE_X - 56 or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    asc, desc = f.getmetrics()
    lh = asc + desc + 4
    bw = max(d.textlength(l, font=f) for l in lines) + 56
    bh = lh * len(lines) + 30
    x0 = (W - bw) / 2
    d.rounded_rectangle([x0, y_top, x0 + bw, y_top + bh], radius=20, fill=(255, 255, 255, 245))
    for i, l in enumerate(lines):
        d.text((x0 + (bw - d.textlength(l, font=f)) / 2, y_top + 15 + i * lh), l, font=f, fill=(0, 0, 0, 255))


# ------------------------------------------------------------------ captions
def chunk_words(words: list[dict], max_words: int = 2, max_chars: int = 16, gap: float = 0.35) -> list[list[dict]]:
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["s"] - cur[-1]["e"] > gap
                    or len(" ".join(x["w"] for x in cur + [w])) > max_chars):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w["w"][-1:] in ".?!":
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def draw_caption(img, chunk, active, *, y_center, color, size=76, upper=True, chunk_scale=1.0, word_scale=1.0,
                 do_censor=True):
    d = ImageDraw.Draw(img)
    raw = " ".join(w["w"] for w in chunk)
    path = caption_font(raw)
    upper = upper and is_latin(raw)
    toks = []
    for w in chunk:
        t = EMOJI_RE.sub("", w["w"]).strip(" ,;:")
        t = censor(t) if do_censor else t
        toks.append(t.upper() if upper else t)
    base = int(size * chunk_scale)
    f = _font(path, base)
    while d.textlength(" ".join(toks), font=f) > W - 2 * SAFE_X and base > 40:
        base -= 4
        f = _font(path, base)
    space = d.textlength(" ", font=f)
    total = sum(d.textlength(t, font=f) for t in toks) + space * (len(toks) - 1)
    x = (W - total) / 2
    asc, desc = f.getmetrics()
    y = y_center - (asc + desc) / 2
    stroke = max(6, base // 9)
    for i, t in enumerate(toks):
        tw = d.textlength(t, font=f)
        emph = bool(PROFANITY.search(chunk[i]["w"]) or HYPE_WORD.match(chunk[i]["w"]))
        if i == active:
            fa = _font(path, int(base * word_scale))
            ta = d.textlength(t, font=fa)
            ya = y - (fa.size - base) * 0.55
            _outlined(d, (x - (ta - tw) / 2, ya), t, fa, _hex(EMPH if emph else color), stroke)
        else:
            _outlined(d, (x, y), t, f, (255, 255, 255, 255), stroke)
        x += tw + space


# ------------------------------------------------------------------ emoji
EMOJI_FONTS = ["/System/Library/Fonts/Apple Color Emoji.ttc", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
               "/usr/share/fonts/noto/NotoColorEmoji.ttf", "C:/Windows/Fonts/seguiemj.ttf"]
_emoji_cache: dict = {}


def emoji_img(ch: str, px: int) -> Image.Image | None:
    key = (ch, px)
    if key in _emoji_cache:
        return _emoji_cache[key]
    for p in EMOJI_FONTS:
        if not Path(p).exists():
            continue
        for size in (160, 137, 109, 96, 64):
            try:
                f = ImageFont.truetype(p, size)
                im = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((size // 2, size // 4), ch, font=f, embedded_color=True)
                bbox = im.getbbox()
                if not bbox:
                    continue
                im = im.crop(bbox)
                im = im.resize((px, int(px * im.height / im.width)), Image.LANCZOS)
                _emoji_cache[key] = im
                return im
            except OSError:
                continue
    _emoji_cache[key] = None
    return None


def pick_emoji(words: list[dict], t: float) -> str:
    near = " ".join(w["w"].lower() for w in words if abs(w["s"] - t) < 2.5)
    if re.search(r"ha(ha)+|lol|lmao|laugh|funny", near):
        return "😂"
    if re.search(r"dead|die|died|kill|crash|rip|over", near):
        return "💀"
    if re.search(r"what|no|how|why|wait|oh", near):
        return "😱"
    return "🔥"


# ------------------------------------------------------------------ audio analysis
def _db_series(src: Path, step: float = 0.1) -> np.ndarray:
    sr = 8000
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(len(x) // (sr * step))
    if n == 0:
        return np.zeros(0)
    blk = x[: int(n * sr * step)].reshape(n, -1)
    return 20 * np.log10(np.sqrt(np.mean(blk ** 2, axis=1)) + 1e-9)


def auto_peaks(src: Path, n: int = 1, min_t: float = 1.2, sep: float = 6.0, rise: float = 13.0) -> list[float]:
    """Only real impact moments: a sharp jump well above the clip's typical level (screams, crashes, explosions)."""
    db = _db_series(src)
    if len(db) < 20:
        return []
    med = float(np.median(db))
    sm = np.convolve(db, np.ones(3) / 3, mode="same")
    out = []
    for i in np.argsort(-sm):
        t = i * 0.1
        if sm[i] < med + rise or len(out) >= n:
            break
        before = float(np.mean(db[max(0, i - 15):max(1, i - 3)]))
        if sm[i] - before < 7:      # must be a jump, not a sustained loud section
            continue
        if t < min_t or t > len(db) * 0.1 - 1.0:
            continue
        if all(abs(t - o) >= sep for o in out):
            out.append(round(float(t), 2))
    return sorted(out)


def tighten_plan(src: Path, words: list[dict], min_gap: float = 0.55, keep_pad: float = 0.12) -> list[tuple]:
    """Keep intervals with dead air (no words AND quiet) removed."""
    db = _db_series(src)
    if len(db) == 0:
        return []
    dur = len(db) * 0.1
    quiet = db < max(float(np.median(db)) - 6, -50)
    spoken = np.zeros(len(db), bool)
    for w in words:
        spoken[max(0, int((w["s"] - 0.15) / 0.1)): int((w["e"] + 0.15) / 0.1) + 1] = True
    dead = quiet & ~spoken
    cuts, i = [], 0
    while i < len(dead):
        if dead[i]:
            j = i
            while j < len(dead) and dead[j]:
                j += 1
            a, b = i * 0.1, j * 0.1
            if b - a >= min_gap:
                cuts.append((a + keep_pad, b - keep_pad))
            i = j
        else:
            i += 1
    if not cuts or sum(b - a for a, b in cuts) < 0.4:
        return []
    keep, cur = [], 0.0
    for a, b in cuts:
        if a > cur:
            keep.append((round(cur, 2), round(a, 2)))
        cur = b
    if cur < dur:
        keep.append((round(cur, 2), round(dur, 2)))
    return keep


def remap(t: float, keep: list[tuple]) -> float | None:
    acc = 0.0
    for a, b in keep:
        if a <= t <= b:
            return acc + (t - a)
        acc += b - a
    return None


def apply_tighten(src: Path, keep: list[tuple], out: Path) -> Path:
    expr = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in keep)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex",
         f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];[0:a]aselect='{expr}',asetpts=N/SR/TB[a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac",
         "-b:a", "192k", str(out)])
    return out


def letterbox(src: Path, sw: int, sh: int) -> tuple[int, int]:
    """Detect cinematic black bars (cutscenes/letterboxed sources) so gameplay fills its panel.
    Uses the most common per-frame crop, so a few bright frames don't cancel it."""
    from collections import Counter
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(src), "-vf", "fps=2,cropdetect=limit=24:round=2:reset=1",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not m:
        return (0, 0)
    rows = [(int(h), int(y)) for _, h, _, y in m]
    barred = [(h, y) for h, y in rows if sh * 0.6 <= h <= sh * 0.95 and (y >= sh * 0.025 or sh - y - h >= sh * 0.025)]
    if len(barred) < max(2, len(rows) * 0.08):   # bars in a real share of the clip (e.g. a cutscene) -> always trim
        return (0, 0)
    h, y = Counter(barred).most_common(1)[0][0]
    return (y, sh - y - h)


def cam_crop(cam: dict) -> tuple[int, int, int, int]:
    """Fit the webcam box to the panel aspect WITHOUT cutting the head: crop around the face, not the centre."""
    x, y, w, h = cam["x"], cam["y"], cam["w"], cam["h"]
    a = W / CAM_H
    fy = cam.get("face_cy", y + h * 0.45)
    fx = cam.get("face_cx", x + w / 2)
    if w / h < a:     # box too tall -> keep full width, choose rows so the face sits at ~42% height
        nh = int(w / a) // 2 * 2
        ny = int(min(max(fy - nh * 0.42, y), y + h - nh))
        return x, ny, w // 2 * 2, nh
    nw = int(h * a) // 2 * 2   # box too wide -> keep full height, centre on the face horizontally
    nx = int(min(max(fx - nw / 2, x), x + w - nw))
    return nx, y, nw, h // 2 * 2


# ------------------------------------------------------------------ sound effects (synthesized, licence-free)
SFX = {
    "whoosh": "anoisesrc=d=0.55:c=pink:a=0.5,highpass=f=400,lowpass=f=5000,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.25",
    "boom": "aevalsrc='0.95*sin(2*PI*(70-40*t)*t)*exp(-3.5*t)+0.25*(random(0)-0.5)*exp(-18*t)':d=1.1:s=48000",
    "pop": "aevalsrc='0.7*sin(2*PI*(1200-900*t)*t)*exp(-28*t)':d=0.18:s=48000",
}


def sfx_file(name: str) -> Path:
    d = Path("~/.clipstudio/sfx").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    custom = ASSETS / "sfx" / f"{name}.wav"
    if custom.exists():
        return custom
    p = d / f"{name}.wav"
    if not p.exists():
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", SFX[name], "-ac", "2", "-ar", "48000", str(p)])
    return p


# ------------------------------------------------------------------ overlay track
def build_overlay(tmp: Path, dur: float, *, words, layout, hook, hook_secs, title, credit, handle, cta, accent,
                  max_words, caption_style, cap_size, emojis, headline_style, do_censor, cam_box_h,
                  hook_start: float = 0.0, tease_text: str = "") -> Path:
    cp = capx.preset(caption_style)
    if max_words:
        cp["words"] = max_words
    if cap_size:
        cp["size"] = cap_size
    chunks = capx.chunk(words, cp) if caption_style != "none" else []
    env = capx.envelope(cp)
    events = {0.0, dur}
    spans = []  # (start, end, chunk_idx, word_idx, anim_frame_or_None)
    for ci, ch in enumerate(chunks):
        c_end = ch[-1]["e"]
        nxt = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else dur
        c_end = nxt if nxt - c_end < 0.5 else c_end + 0.15
        for wi, w in enumerate(ch):
            s0 = ch[0]["s"] if wi == 0 else w["s"]
            e0 = ch[wi + 1]["s"] if wi + 1 < len(ch) else c_end
            s0, e0 = max(0.0, s0), min(dur, e0)
            if e0 - s0 <= 0.01:
                continue
            t = s0
            for k in range(len(env)):
                b2 = min(s0 + (k + 1) / FPS, e0)
                if b2 > t:
                    spans.append((t, b2, ci, wi, k))
                    events.update({t, b2})
                t = b2
            if e0 > t:
                spans.append((t, e0, ci, wi, None))
                events.update({t, e0})
    emo_spans = []
    for t, ch in emojis:
        for off, sc in [(0.0, 0.6), (0.06, 1.15), (0.12, 1.0)]:
            a = t + off
            b = t + (0.06 if off < 0.06 else (0.12 if off < 0.12 else 1.3))
            if a < dur:
                emo_spans.append((a, min(b, dur), ch, sc))
                events.update({a, min(b, dur)})
    hook_words = len(hook.replace("*", "").split()) if hook else 0
    REVEAL = 0.07  # hook words pop in one by one (fast enough to read in < 1 s)
    if hook:
        events.update(hook_start + k * REVEAL for k in range(hook_words + 1))
        if hook_start:
            events.add(hook_start)
    hook_end = hook_start + hook_secs if hook and hook_secs else None
    if hook_end and hook_end < dur:
        events.add(hook_end)
    # 'top' = persistent question hook at the top (Sidemen style); default for non-facecam layouts
    top_style = headline_style == "top" or (headline_style in ("auto", "outline") and layout != "facecam"
                                            and not hook_secs)
    cta_start = max(0.0, dur - 2.0) if cta else None
    if cta_start:
        events.add(cta_start)
    times = sorted(t for t in events if 0 <= t <= dur)

    if layout == "facecam":
        cap_y, head_y = CAM_H + 300, CAM_H
    elif layout == "blur":
        cap_y, head_y = BLUR_VID_Y + 608 + 150, BLUR_VID_Y - 170
    elif layout == "track":
        cap_y, head_y = 1420, 300
    else:
        cap_y, head_y = 1180, 330

    cache: dict = {}
    entries = []
    body = body_font_path()
    for a, b in zip(times, times[1:]):
        if b - a < 1e-3:
            continue
        mid = (a + b) / 2
        sp = next((s for s in spans if s[0] <= mid < s[1]), None)
        em = next((e for e in emo_spans if e[0] <= mid < e[1]), None)
        show_hook = bool(hook) and mid >= hook_start and (not hook_end or mid < hook_end)
        reveal = min(hook_words, int((mid - hook_start) / REVEAL) + 1) if show_hook else 0
        in_tease = bool(tease_text) and mid < hook_start
        show_cta = cta_start is not None and mid >= cta_start
        key = (sp[2:] if sp else None, em[2:] if em else None, show_hook, reveal, in_tease, show_cta)
        if key not in cache:
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            if credit:
                f = _font(body if is_latin(credit) else font_for(credit, display=False), 24, 700)
                tw = d.textlength(credit, font=f)
                d.rounded_rectangle([28, 34, 28 + tw + 28, 76], radius=21, fill=(0, 0, 0, 120))
                d.text((42, 41), credit, font=f, fill=(255, 255, 255, 220))
            shown_hook = " ".join(hook.split()[:reveal]) if show_hook else ""
            if in_tease:
                draw_headline(img, tease_text, head_y if layout == "facecam" else 330, accent=accent, size=70,
                              backing=True)
            elif show_hook and shown_hook and not show_cta:
                if headline_style == "box":
                    draw_box_headline(img, shown_hook, head_y - 60)
                elif top_style:
                    draw_headline(img, shown_hook, 250 if layout != "blur" else head_y - 40, accent=accent,
                                  size=84, max_lines=3, backing=False, color=_hex(accent), emph_color=(255, 255, 255, 255),
                                  fontfile=str(ASSETS / "fonts" / "Anton-Regular.ttf"))
                else:
                    draw_headline(img, shown_hook, head_y, accent=accent, size=58 if layout == "facecam" else 64,
                                  backing=layout != "blur")
            elif title and not show_cta and not show_hook:
                draw_headline(img, title, head_y, accent=accent, size=58 if layout == "facecam" else 64,
                              backing=layout != "blur")
            if handle:
                f = _font(body, 28, 700)
                d.text(((W - d.textlength(handle, font=f)) / 2, H - 520), handle, font=f, fill=(255, 255, 255, 120))
            if sp and not show_cta:
                capx.draw(img, chunks[sp[2]], sp[3], p=cp, y_center=cap_y, chunk_idx=sp[2], k=sp[4],
                          do_censor=do_censor)
            if em:
                ei = emoji_img(em[2], int(150 * em[3]))
                if ei:
                    ey = (BLUR_VID_Y + 608 + 10) if layout == "blur" else cap_y - 120
                    img.alpha_composite(ei, (int(W - SAFE_X - 100 - ei.width / 2), int(ey - ei.height / 2)))
            if show_cta:
                draw_headline(img, cta, H // 2 - 150, accent=accent, size=78)
            p = tmp / f"ov_{len(cache):04d}.png"
            img.save(p, compress_level=1)
            cache[key] = p
        entries.append((cache[key], b - a))
    lst = tmp / "overlay.txt"
    with open(lst, "w") as f:
        for p, du in entries:
            f.write(f"file '{p}'\nduration {du:.3f}\n")
        f.write(f"file '{entries[-1][0]}'\n")
    return lst


# ------------------------------------------------------------------ music
def pick_music(music: str | None) -> Path | None:
    if music in (None, "", "none"):
        return None
    from . import sound
    if music in sound.BEATS or music == "beat":
        return sound.beat("phonk" if music == "beat" else music)   # original synthesized loop, licence-free
    p = Path(music).expanduser()
    if p.is_file():
        return p
    folder = p if p.is_dir() else None
    if music == "auto":
        cfg_dir = load_config().get("music_dir")
        folder = Path(cfg_dir).expanduser() if cfg_dir else ASSETS / "music"
    if folder and folder.is_dir():
        tracks = [t for t in folder.iterdir() if t.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg", ".aac")]
        if tracks:
            return random.choice(tracks)
    if music == "auto":
        from . import sound
        log("no music tracks in assets/music -> using an original synthesized beat")
        return sound.beat(random.choice(list(sound.BEATS)))
    log("music not found — rendering without music")
    return None


# ------------------------------------------------------------------ main render
def render(src: Path, out: Path, *, words: list[dict], layout: str = "auto", trim: tuple | None = None,
           cam: dict | None = None, focus: float = 0.5, hook: str = "", hook_secs: float = 3.5, title: str = "",
           credit: str = "", handle: str = "", cta: str = "", music: str | None = None, music_db: float | None = None,
           punch: list[float] | None = None, progress: bool = False, caption_style: str | None = None,
           max_words: int | None = None, accent: str | None = None, tighten: bool = True, auto_punch: bool = True,
           emoji: str | None = "auto", sfx: bool | str = "auto", cap_size: int | None = None, headline_style: str = "outline",
           do_censor: bool = True, grade: bool = True, zoomcuts: bool = True, tease: bool | str = False) -> dict:
    cfg = load_config()
    rcfg = cfg.get("render", {})
    accent = accent or rcfg.get("accent", "#FFE600")
    caption_style = caption_style or rcfg.get("caption_style", "auto")
    max_words = max_words or int(rcfg.get("max_words_per_line", 0) or 0) or None   # None = the preset's own
    cap_size = cap_size or int(rcfg.get("caption_size", 0) or 0) or None
    music_db = cfg.get("music_volume_db", -22) if music_db is None else music_db
    tmp = Path(tempfile.mkdtemp(prefix="cs_render_"))

    # ---- trim, then cut dead air
    full = ffprobe_duration(src)
    t0, t1 = trim or (0, full)
    t1 = min(t1, full)
    words = [{"w": w["w"], "s": round(w["s"] - t0, 3), "e": round(w["e"] - t0, 3)} for w in words
             if w["e"] > t0 and w["s"] < t1]
    punch = [p - t0 for p in (punch or [])]
    work = src
    if trim:
        work = tmp / "trim.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-i", str(src), "-t", f"{t1 - t0:.3f}", "-c:v",
             "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", str(work)])
    removed = 0.0
    if tighten:
        keep = tighten_plan(work, words)
        if keep:
            before = ffprobe_duration(work)
            work = apply_tighten(work, keep, tmp / "tight.mp4")
            removed = before - ffprobe_duration(work)
            nw = []
            for w in words:
                s, e = remap(w["s"], keep), remap(w["e"], keep)
                if s is not None:
                    nw.append({"w": w["w"], "s": round(s, 3), "e": round(e if e is not None else s + 0.25, 3)})
            words = nw
            punch = [x for x in (remap(p, keep) for p in punch) if x is not None]
            log(f"tightened: removed {removed:.1f}s of dead air")
    dur = ffprobe_duration(work)
    if auto_punch and not punch:
        punch = auto_peaks(work)
    # cold-open tease: flash the payoff first ("wait for it"), then the clip plays from the start
    hook_start = 0.0
    if tease and punch:
        p0 = punch[0]
        a0, b0 = max(0.0, p0 - 0.6), min(dur, p0 + 0.9)
        tz = tmp / "tease.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(work), "-filter_complex",
             f"[0:v]trim={a0:.3f}:{b0:.3f},setpts=PTS-STARTPTS[tv];[0:a]atrim={a0:.3f}:{b0:.3f},asetpts=PTS-STARTPTS[ta];"
             f"[0:v]setpts=PTS-STARTPTS[mv];[0:a]asetpts=PTS-STARTPTS[ma];[tv][ta][mv][ma]concat=n=2:v=1:a=1[v][a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac",
             str(tz)])
        td = b0 - a0
        work = tz
        words = [{"w": w["w"], "s": round(w["s"] + td, 3), "e": round(w["e"] + td, 3)} for w in words]
        punch = [round(p0 - a0, 3)] + [p + td for p in punch]
        dur = ffprobe_duration(work)
        hook_start = td
        log(f"cold-open tease: {td:.1f}s of the payoff first")

    emojis = []
    if emoji and emoji != "none":
        for p in punch:
            emojis.append((p, emoji if emoji != "auto" else pick_emoji(words, p)))
        if emoji == "auto":   # keyword emoji pops (max 3, spaced >= 4 s, away from punches)
            for w in words:
                e = capx.emoji_for(w["w"]) if capx.is_key(w["w"]) or len(w["w"]) > 4 else None
                if e and len(emojis) < 3 and all(abs(w["s"] - t) > 4 for t, _ in emojis):
                    emojis.append((w["s"], e))

    # ---- layout
    sw, sh = ffprobe_size(work)
    lb = letterbox(work, sw, sh)   # (top, bottom) black bars inside the game image

    if layout in ("auto", "facecam") and not cam:
        det = fc.detect(work)
        if det and not det.get("fullcam"):
            layout, cam = "facecam", det
            log(f"facecam detected at {det}")
        elif layout == "facecam":
            log("no stable webcam found -> blur layout (pass --facecam x,y,w,h to force)")
            layout = "blur"
        else:
            layout = "track" if (det and det.get("fullcam")) else "blur"

    if layout == "track":   # follow the active speaker, hard cuts between subjects
        from . import track
        holds = track.plan(work)
        cw, xexpr = track.crop_expr(holds, sw, sh)
        base = f"[0:v]crop={cw}:{sh}:x='{xexpr}':y=0,scale={W}:{H},setsar=1[base]"
        log(f"auto-reframe: {len(holds)} shot(s)")
    elif layout == "fill":
        sc_w = int(sw * H / (sh - lb[0] - lb[1])) // 2 * 2
        x = int((sc_w - W) * min(max(focus, 0), 1))
        base = f"[0:v]crop={sw}:{sh - lb[0] - lb[1]}:0:{lb[0]},scale={sc_w}:{H},crop={W}:{H}:{x}:0,setsar=1[base]"
    elif layout == "blur":
        fg_h = int(sh * W / sw) // 2 * 2
        base = (f"[0:v]split[a][b];[a]scale=-2:{H},crop={W}:{H},scale=270:-2,gblur=sigma=18,scale=-2:{H},crop={W}:{H},eq=brightness=-0.30:saturation=1.25[bg];"
                f"[b]scale={W}:{fg_h}[fg];[bg][fg]overlay=0:{BLUR_VID_Y},setsar=1[base]")
    elif layout == "facecam":
        cx, cy, cw, ch = cam_crop(cam)
        game_h = H - CAM_H
        gh_src = sh - lb[0] - lb[1]
        gw = max(W, int(sw * game_h / gh_src) // 2 * 2)
        gx = int((gw - W) * min(max(focus, 0), 1))
        # keep the streamer's webcam out of the gameplay panel (no double faces):
        # slide the crop window away from it if possible, otherwise blur it out
        k = gw / sw                                   # source px -> scaled gameplay px
        bx0, bx1 = cam["x"] * k, (cam["x"] + cam["w"]) * k
        game_pre = ""
        if bx0 < gx + W and bx1 > gx:                 # webcam overlaps the gameplay window
            if bx1 <= gw - W and (cam["x"] + cam["w"] / 2) < sw / 2:
                gx = int(bx1)                         # cam on the left -> start right of it
            elif bx0 >= W and (cam["x"] + cam["w"] / 2) >= sw / 2:
                gx = int(bx0 - W)                     # cam on the right -> end left of it
            else:
                ox, oy, ow, oh = cam["x"], max(0, cam["y"] - lb[0]), cam["w"], cam["h"]
                game_pre = (f"split[g1][g2];[g2]crop={ow}:{oh}:{ox}:{oy},gblur=sigma=40,"
                            f"eq=brightness=-0.15[gb];[g1][gb]overlay={ox}:{oy},")
        base = (f"[0:v]split[a][b];[a]crop={cw}:{ch}:{cx}:{cy},scale={W}:{CAM_H}[cam];[b]crop={sw}:{gh_src}:0:{lb[0]},{game_pre}scale={gw}:{game_h},crop={W}:{game_h}:{gx}:0[game];"
                f"[cam][game]vstack,setsar=1[base]")
    else:
        die(f"unknown layout {layout}")

    fx = ""
    if grade:
        fx += ";[base]eq=contrast=1.06:saturation=1.18,unsharp=5:5:0.5[base]"
    # zoom cuts: alternate framing between phrases (1.00 / 1.06) like an editor's jump-cut punch-ins
    zc = ""
    zoom_bounds: list[float] = []
    if zoomcuts and words:
        bounds, last = [0.0], 0.0
        for w0, w1 in zip(words, words[1:]):
            if w1["s"] - w0["e"] > 0.35 and w1["s"] - last > 2.2:
                bounds.append(w1["s"])
                last = w1["s"]
        zoom_bounds = bounds[1:]
        bounds.append(dur)
        zc = "+".join(f"0.06*gte(t,{a:.2f})*lt(t,{b:.2f})" for i, (a, b) in enumerate(zip(bounds, bounds[1:]))
                      if i % 2 == 1)
    if punch or zc:
        z = "+".join([f"0.13*exp(-4*(t-{p:.2f}))*between(t,{p:.2f},{p + 1.2:.2f})" for p in punch] + ([zc] if zc else []))
        sx = "+".join(f"16*sin(95*t)*exp(-7*(t-{p:.2f}))*between(t,{p:.2f},{p + 0.5:.2f})" for p in punch) or "0"
        sy = "+".join(f"12*cos(80*t)*exp(-7*(t-{p:.2f}))*between(t,{p:.2f},{p + 0.5:.2f})" for p in punch) or "0"
        fx += (f";[base]scale=w='trunc({W}*(1.02+{z})/2)*2':h='trunc({H}*(1.02+{z})/2)*2':eval=frame,"
               f"crop={W}:{H}:x='(iw-{W})/2+{sx}':y='(ih-{H})/2+{sy}'[base]")
        for p in punch:   # warm color flash on impact (clip-channel style), not a flat white flash
            fx += (f";[base]colorbalance=rs=0.35:gs=0.05:bs=-0.25:rm=0.2:bm=-0.15:"
                   f"enable='between(t,{p:.2f},{p + 0.12:.2f})',eq=brightness=0.08:"
                   f"enable='between(t,{p:.2f},{p + 0.05:.2f})'[base]")
    for b in zoom_bounds:   # whip-blur on zoom cuts: 2 frames of horizontal motion blur
        fx += f";[base]avgblur=sizeX=26:sizeY=1:enable='between(t,{b - 0.034:.3f},{b + 0.034:.3f})'[base]"

    style_reason = ""
    if (caption_style or "auto") == "auto":
        caption_style, style_reason = capx.auto_style(words, layout=layout, punches=len(punch))
        log(f"caption style: {caption_style} ({style_reason})")
    lst = build_overlay(tmp, dur, words=words, layout=layout, hook=hook, hook_secs=hook_secs, title=title,
                        credit=credit, handle=handle, cta=cta, accent=accent, max_words=max_words,
                        caption_style=caption_style, cap_size=cap_size, emojis=emojis,
                        headline_style=headline_style, do_censor=do_censor, cam_box_h=CAM_H,
                        hook_start=hook_start, tease_text=(tease if isinstance(tease, str) else "WAIT FOR IT 👀")
                        if tease and hook_start else "")
    inputs = ["-i", str(work), "-f", "concat", "-safe", "0", "-i", str(lst)]
    graph = (base + fx + f";[1:v]format=rgba,fps={FPS}[ov];[base]fps={FPS}[b30];"
             f"[b30][ov]overlay=0:0:format=auto:shortest=1[v0]")
    vout = "[v0]"
    nin = 2
    if progress:
        r, g, b = _hex(accent)[:3]
        inputs += ["-f", "lavfi", "-i", f"color=c=0x{r:02x}{g:02x}{b:02x}:s={W}x8:r={FPS}:d={dur:.3f}"]
        graph += f";[v0][{nin}:v]overlay=x='-W+W*t/{dur:.3f}':y={H - 8}:shortest=1[v1]"
        vout = "[v1]"
        nin += 1

    # ---- audio: voice (+music ducked) + sfx -> -14 LUFS
    graph += ";[0:a]aresample=48000,aformat=channel_layouts=stereo[voice0]"
    voice = "[voice0]"
    track = pick_music(music)
    if track:
        inputs += ["-stream_loop", "-1", "-i", str(track)]
        graph += (f";{voice}asplit[voice1][key];[{nin}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"volume={music_db}dB[mus];[mus][key]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350[duck];"
                  f"[voice1][duck]amix=inputs=2:duration=first:normalize=0[voice2]")
        voice = "[voice2]"
        nin += 1
    from . import sound
    actions = [w["s"] for w in words if capx.ACTION.match(w["w"].strip())]
    fxs = sound.plan(dur, hook=bool(hook), hook_secs=hook_secs if hook else 0, hook_at=hook_start, punches=punch,
                     zoom_bounds=zoom_bounds, emojis=[t for t, _ in emojis], actions=actions, cta=bool(cta),
                     level=sfx if isinstance(sfx, str) else ("auto" if sfx else "off"))
    labels = []
    for k, (name, at, vol) in enumerate(fxs):
        inputs += ["-i", str(sound.sfx(name))]
        ms = int(at * 1000)
        graph += f";[{nin}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol * 0.5:.3f},adelay={ms}|{ms}[s{k}]"
        labels.append(f"[s{k}]")
        nin += 1
    if labels:
        graph += f";{voice}{''.join(labels)}amix=inputs={1 + len(labels)}:duration=first:normalize=0[mixed]"
        voice = "[mixed]"
    graph += (f";{voice}afade=t=out:st={max(dur - 0.35, 0):.2f}:d=0.35,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", vout, "-map", "[aout]",
           "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    r = run(cmd, check=False)
    if r.returncode != 0:
        (tmp / "graph.txt").write_text(graph)
        die(f"render failed: {r.stderr[-1500:]}\n(graph saved in {tmp}/graph.txt)")
    shutil.rmtree(tmp, ignore_errors=True)
    return {"out": str(out), "layout": layout, "cam": cam, "duration": round(dur, 2), "dead_air_removed": round(removed, 1),
            "punches": punch, "emojis": [e[1] for e in emojis], "caption_style": caption_style,
            "style_reason": style_reason, "music": str(track) if track else None}


def cover(src: Path, t: float, title: str, out: Path, accent: str = "#FFE600") -> Path:
    """Cover/thumbnail: a strong frame + big outlined title."""
    tmp = Path(tempfile.mkstemp(suffix=".jpg")[1])
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(tmp)])
    img = Image.open(tmp).convert("RGBA")
    if img.size != (W, H):
        img = img.resize((W, H))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle([0, 760, W, 1160], fill=(0, 0, 0, 90))
    img.alpha_composite(shade)
    draw_headline(img, title, 960, accent=accent, size=100, max_lines=3)
    img.convert("RGB").save(out, quality=92)
    tmp.unlink(missing_ok=True)
    return out
