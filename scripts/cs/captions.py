"""Caption engine: animated, auto-sizing caption presets modelled on what top viral shorts use.

Presets (pick with --style):
  stream     1 word at a time, condensed bold, white/yellow alternating, heavy outline, pop-in  (stream-clip channels)
  hormozi    2 words, Anton caps, key word green, pop                                         (talking / commentary)
  beast      1-2 words, chunky cartoon font, yellow active word, slight tilt, bounce            (high-energy)
  box        2-3 words, Montserrat Black, colored plate behind the spoken word                 ("viral orange box")
  karaoke    3-4 words on screen, highlight follows the voice, upcoming words dimmed
  spotlight  1 glowing word, center
  neon       Bebas with neon glow
  minimal    sentence case, small, soft shadow                                                 (clean / explainer)
Shared smarts: auto-size (short words grow, long words shrink to fit), automatic emphasis (numbers, hype words,
swears, SHOUTED words -> bigger + emphasis color), per-frame pop animation, *ACTION* captions for non-speech
([laughs] -> *LAUGHS*), keyword emoji suggestions, swear censoring.
"""
from __future__ import annotations

import random
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .util import ASSETS, body_font_path, font_for, is_latin

W = 1080
SAFE_X = 90
FONTS = ASSETS / "fonts"


def _f(name: str) -> str:
    p = FONTS / name
    return str(p) if p.exists() else body_font_path()


PRESETS = {
    "stream": dict(font="Anton-Regular.ttf", size=96, words=1, upper=True, colors=["#FFFFFF", "#FFE600"],
                   emph="#FF3B3B", mode="color", stroke=0.12, rotate=0, glow=False, anim="pop"),
    "hormozi": dict(font="Anton-Regular.ttf", size=92, words=2, upper=True, colors=["#FFFFFF"], active="#3DFF6E",
                    emph="#FFD400", mode="active", stroke=0.11, rotate=0, glow=False, anim="pop"),
    "beast": dict(font="LuckiestGuy-Regular.ttf", size=86, words=2, upper=True, colors=["#FFFFFF"], active="#FFE600",
                  emph="#FF4040", mode="active", stroke=0.14, rotate=4, glow=False, anim="bounce"),
    "box": dict(font="Montserrat-Variable.ttf", size=74, words=3, upper=True, colors=["#FFFFFF"], active="#FF7A00",
                emph="#FF7A00", mode="box", stroke=0.10, rotate=0, glow=False, anim="pop"),
    "karaoke": dict(font="Montserrat-Variable.ttf", size=70, words=4, upper=True, colors=["#FFFFFF"],
                    active="#FFE600", emph="#FF4D4D", mode="karaoke", stroke=0.10, rotate=0, glow=False, anim="pop"),
    "spotlight": dict(font="Montserrat-Variable.ttf", size=104, words=1, upper=True, colors=["#FFFFFF"],
                      emph="#FFE600", mode="color", stroke=0.06, rotate=0, glow="#FFFFFF", anim="pop"),
    "neon": dict(font="BebasNeue-Regular.ttf", size=118, words=2, upper=True, colors=["#FFFFFF"], active="#00F0FF",
                 emph="#FF2BD6", mode="active", stroke=0.05, rotate=0, glow="#00F0FF", anim="pop"),
    "minimal": dict(font="Montserrat-Variable.ttf", size=56, words=4, upper=False, colors=["#FFFFFF"],
                    active="#FFFFFF", emph="#FFE600", mode="active", stroke=0.0, rotate=0, glow=False, anim="fade"),
}
ALIASES = {"pop": "hormozi", "plain": "minimal", "kai": "stream", "mrbeast": "beast", "viral": "stream"}

ENVELOPE = {  # scale per frame after a word/chunk appears (30 fps)
    "pop": [0.62, 1.16, 1.06, 0.98, 1.0],
    "bounce": [0.5, 1.22, 0.92, 1.06, 0.99, 1.0],
    "fade": [0.97, 0.99, 1.0],
}

PROFANITY = re.compile(r"\b(fuck\w*|shit\w*|bitch\w*|cunt|motherfuck\w*|nigg\w*|fag\w*|retard\w*)\b", re.I)
HYPE = re.compile(r"^(no+|what+|bro+|yo+|oh+|omg|wow+|yes+|run+|go+|dude|insane|crazy|holy|dead|help|stop|wait|"
                  r"never|crash\w*|died?|kill\w*|win\w*|lost|money|million\w*|free|first|last|worst|best)$", re.I)
ACTION = re.compile(r"^[\[\(\*](.+?)[\]\)\*]$")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF️‍]+")
EMOJI_MAP = [
    (r"laugh|haha|lol|lmao|funny", "😂"), (r"dead|die|died|kill|rip|crash", "💀"), (r"fire|hot|insane|crazy", "🔥"),
    (r"money|cash|dollar|rich|million", "💰"), (r"car|drive|race|fast|speed", "🏎️"), (r"cop|police|arrest|jail", "🚨"),
    (r"love|girl|date|kiss", "❤️"), (r"what|how|why|wait|omg|no way", "😱"), (r"win|won|goat|best", "🏆"),
    (r"plane|fly|jet", "✈️"), (r"gun|shoot|shot", "🔫"), (r"boat|water|ocean", "🌊"), (r"cry|sad", "😭"),
]


def preset(name: str | None) -> dict:
    name = ALIASES.get((name or "stream").lower(), (name or "stream").lower())
    p = dict(PRESETS.get(name, PRESETS["stream"]))
    p["name"] = name
    return p


def hex2(c: str, a: int = 255) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def font(path: str, size: int, weight: int = 900) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, max(10, int(size)))
    if "Variable" in path:
        try:
            f.set_variation_by_axes([weight])
        except Exception:  # noqa: BLE001
            pass
    return f


def censor(w: str) -> str:
    return PROFANITY.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 2) + m.group(0)[-1], w)


def clean_token(w: str, upper: bool, do_censor: bool) -> str:
    a = ACTION.match(w.strip())
    if a:
        return "*" + a.group(1).strip().upper() + "*"
    t = EMOJI_RE.sub("", w).strip(" ,;:")
    t = censor(t) if do_censor else t
    return t.upper() if upper and is_latin(t) else t


def is_key(w: str) -> bool:
    raw = w.strip(".,!?;:\"'").strip()
    return bool(re.search(r"\d", raw) or HYPE.match(raw) or PROFANITY.search(raw) or ACTION.match(w.strip())
                or (raw.isupper() and len(raw) > 2) or w.endswith("!"))


def emoji_for(text: str) -> str | None:
    t = text.lower()
    for pat, e in EMOJI_MAP:
        if re.search(pat, t):
            return e
    return None


FILLER = re.compile(r"^(um+|uh+|erm+|hmm+|mm+|uhm+|ah+)[,.!?]*$", re.I)


def chunk(words: list[dict], p: dict, gap: float = 0.35) -> list[list[dict]]:
    n, max_chars = p["words"], {1: 14, 2: 16, 3: 22, 4: 28}.get(p["words"], 22)
    out, cur = [], []
    for w in words:
        if FILLER.match(w["w"].strip()):          # pro editors drop "um/uh" from captions
            continue
        if ACTION.match(w["w"].strip()):           # action captions stand alone
            if cur:
                out.append(cur)
            out.append([w])
            cur = []
            continue
        if cur and (len(cur) >= n or w["s"] - cur[-1]["e"] > gap
                    or len(" ".join(x["w"] for x in cur + [w])) > max_chars):
            out.append(cur)
            cur = []
        cur.append(w)
        if w["w"][-1:] in ".?!":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def envelope(p: dict) -> list[float]:
    return ENVELOPE.get(p["anim"], ENVELOPE["pop"])


def _layer_text(d, xy, text, f, fill, stroke_w, shadow=True):
    x, y = xy
    if shadow and stroke_w:
        d.text((x + stroke_w * 0.5, y + stroke_w * 0.9), text, font=f, fill=(0, 0, 0, 140), stroke_width=stroke_w,
               stroke_fill=(0, 0, 0, 140))
    d.text((x, y), text, font=f, fill=fill, stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255))


def draw(img: Image.Image, ch: list[dict], active: int, *, p: dict, y_center: int, chunk_idx: int, k: int | None,
         do_censor: bool = True, max_w: int = W - 2 * SAFE_X):
    """Draw one caption state. k = frames since the current word started (None = settled)."""
    env = envelope(p)
    s_word = env[min(k, len(env) - 1)] if k is not None else 1.0
    entering = active == 0 and p["mode"] != "karaoke" or p["words"] == 1
    s_chunk = s_word if entering else 1.0
    s_active = 1.0 if entering else (1.0 + (s_word - 1.0) * 0.8)

    raw_text = " ".join(w["w"] for w in ch)
    path = _f(p["font"]) if is_latin(raw_text) else font_for(raw_text)
    toks = [clean_token(w["w"], p["upper"], do_censor) for w in ch]
    keys = [is_key(w["w"]) for w in ch]
    action = len(ch) == 1 and toks[0].startswith("*")

    # auto-size: base size, short words bigger, long lines shrink to fit
    base = p["size"]
    if p["words"] == 1:
        L = max(1, len(toks[0]))
        base = int(base * max(0.8, min(1.32, 7.5 / L + 0.35)))
        if keys[0] and not action:
            base = int(base * 1.12)
    if action:
        base = int(p["size"] * 0.78)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sizes = []
    for i, t in enumerate(toks):
        sz = base * (1.22 if keys[i] and p["words"] > 1 else 1.0)
        sizes.append(sz)
    fonts = [font(path, sizes[i] * s_chunk) for i in range(len(toks))]
    space = d.textlength(" ", font=fonts[0])
    total = sum(d.textlength(t, font=fonts[i]) for i, t in enumerate(toks)) + space * (len(toks) - 1)
    if total > max_w:
        sc = max_w / total
        fonts = [font(path, sizes[i] * s_chunk * sc) for i in range(len(toks))]
        space = d.textlength(" ", font=fonts[0])
        total = sum(d.textlength(t, font=fonts[i]) for i, t in enumerate(toks)) + space * (len(toks) - 1)
    x = (W - total) / 2
    asc = max(f.getmetrics()[0] for f in fonts)
    for i, t in enumerate(toks):
        f = fonts[i]
        if i == active and s_active != 1.0:
            f = font(path, f.size * s_active)
        tw = d.textlength(t, font=fonts[i])
        aw = d.textlength(t, font=f)
        fa, fd = f.getmetrics()
        tx = x - (aw - tw) / 2
        ty = y_center - asc / 2 - (fa - fonts[i].getmetrics()[0]) * 0.6 - fa * 0.12
        stroke_w = max(0, int(f.size * p["stroke"]))
        # colour logic
        if action:
            fill = (255, 255, 255, 255)
        elif p["mode"] == "color":                      # whole chunk one colour, alternating
            fill = hex2(p["emph"]) if keys[i] else hex2(p["colors"][chunk_idx % len(p["colors"])])
        elif p["mode"] == "karaoke":
            if i < active:
                fill = (255, 255, 255, 255)
            elif i == active:
                fill = hex2(p["active"])
            else:
                fill = (255, 255, 255, 120)
        else:
            fill = hex2(p.get("active", "#FFE600")) if i == active else (
                hex2(p["emph"]) if keys[i] else hex2(p["colors"][0]))
        if p["mode"] == "box" and i == active:
            pad = f.size * 0.2
            bb = d.textbbox((tx, ty), t, font=f)
            d.rounded_rectangle([bb[0] - pad, bb[1] - pad * 0.75, bb[2] + pad, bb[3] + pad * 0.75],
                                radius=int(f.size * 0.2), fill=hex2(p["active"]))
            d.text((tx, ty), t, font=f, fill=(255, 255, 255, 255))
            x += tw + space
            continue
        if p["glow"]:
            g = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(g).text((tx, ty), t, font=f, fill=hex2(p["glow"] if i != active else
                                                                 p.get("active", p["glow"])))
            layer.alpha_composite(g.filter(ImageFilter.GaussianBlur(f.size * 0.18)))
            layer.alpha_composite(g.filter(ImageFilter.GaussianBlur(f.size * 0.06)))
        _layer_text(d, (tx, ty), t, f, fill, stroke_w, shadow=p["stroke"] > 0)
        if p["stroke"] == 0:  # minimal: soft shadow instead of outline
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((tx + 2, ty + 4), t, font=f, fill=(0, 0, 0, 200))
            layer = Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)), layer)
            d = ImageDraw.Draw(layer)
        x += tw + space
    if p["rotate"]:
        ang = random.Random(chunk_idx * 7919).uniform(-p["rotate"], p["rotate"])
        layer = layer.rotate(ang, resample=Image.BICUBIC, center=(W / 2, y_center))
    img.alpha_composite(layer)


def preview_sheet(out, frame_path, styles: list[str] | None = None):
    """One image with every caption style on the same frame, so the user can pick."""
    styles = styles or list(PRESETS)
    sample = [{"w": "he", "s": 0, "e": .3}, {"w": "crashed", "s": .3, "e": .6}, {"w": "the", "s": .6, "e": .9},
              {"w": "plane", "s": .9, "e": 1.2}]
    tiles = []
    base = Image.open(frame_path).convert("RGBA").resize((W, 1920))
    for i, name in enumerate(styles):
        p = preset(name)
        img = base.copy()
        words = sample[: max(1, p["words"])] if p["words"] > 1 else [sample[1]]
        draw(img, words, min(1, len(words) - 1), p=p, y_center=1150, chunk_idx=1, k=None)
        dd = ImageDraw.Draw(img)
        lab = font(body_font_path(), 64, 800)
        dd.rounded_rectangle([40, 60, 60 + dd.textlength(name, font=lab) + 40, 160], radius=24, fill=(0, 0, 0, 200))
        dd.text((70, 72), name, font=lab, fill=(255, 230, 0, 255))
        tiles.append(img.resize((360, 640)))
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (360 * cols, 640 * rows), "black")
    for i, t in enumerate(tiles):
        sheet.paste(t.convert("RGB"), ((i % cols) * 360, (i // cols) * 640))
    sheet.save(out, quality=88)
    return out


def auto_style(words: list[dict], *, layout: str, punches: int = 0, has_burned_captions: bool = False) -> tuple[str, str]:
    """Pick the caption style that fits this clip best. Returns (style, reason)."""
    if has_burned_captions:
        return "none", "source already has captions"
    spoken = [w for w in words if not ACTION.match(w["w"].strip()) and not FILLER.match(w["w"].strip())]
    if not spoken:
        return "spotlight", "almost no speech: one big glowing word only when someone talks"
    span = max(1.0, spoken[-1]["e"] - spoken[0]["s"])
    wps = len(spoken) / span
    keys = sum(is_key(w["w"]) for w in spoken) / len(spoken)
    if len(spoken) < 12:
        return "spotlight", f"only {len(spoken)} words: single glowing words land harder"
    if keys > 0.22 or punches >= 2:
        return "beast", f"high energy ({keys:.0%} hype words, {punches} impacts): bouncy cartoon captions"
    if layout == "track" and wps >= 3.2:
        return "karaoke", f"fast talker ({wps:.1f} words/s) on camera: karaoke keeps up"
    if layout == "track":
        return "hormozi", f"talking head ({wps:.1f} words/s): 2-word Hormozi style"
    if layout == "facecam":
        return "stream", "stream with facecam: one-word pop like top stream-clip channels"
    if wps < 1.6:
        return "minimal", f"calm narration ({wps:.1f} words/s): clean minimal subtitles"
    return "box", "gameplay/commentary video: colored box on the spoken word"
