"""Sound design: a synthesized SFX kit + original beat loops, and auto-placement rules from viral edits.

Everything is generated with numpy, so it's 100% licence-free (no Content ID claims).
Drop your own files in assets/sfx/<name>.wav or assets/music/ to override.

Placement (what top short-form editors do):
  hook appears        -> heavy whoosh + hit          (pattern interrupt in the first frame)
  impact / payoff     -> riser into deep impact      (tension -> release), + whip on the shake
  zoom cut            -> light whip                  (movement gets a sound)
  emoji / keyword pop -> pop
  *ACTION* caption    -> hit
  hook -> title swap  -> click
  end card / reveal   -> ding
Levels: SFX ~6 dB under the voice, music bed low (~-21 dB) and ducked under speech.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .util import ASSETS

SR = 48000
CACHE = Path("~/.clipstudio/sfx").expanduser()
MUSIC_CACHE = Path("~/.clipstudio/music").expanduser()


def _env(n, attack=0.005, decay=None):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    d = np.exp(-t * decay) if decay else 1.0
    return a * d


def _noise(n, seed=0):
    return np.random.default_rng(seed).standard_normal(n)


def _bandsweep(x, f0, f1):
    """Cheap time-varying bandpass: one-pole HP+LP with moving cutoffs."""
    n = len(x)
    fc = np.geomspace(f0, f1, n)
    y = np.zeros(n)
    lp = hp_prev_x = hp = 0.0
    for i in range(n):
        a = np.exp(-2 * np.pi * fc[i] / SR)
        lp = (1 - a) * x[i] + a * lp            # low-pass at fc*2
        hp = a * (hp + lp - hp_prev_x)          # high-pass at fc
        hp_prev_x = lp
        y[i] = hp
    return y


def _norm(x, peak=0.9):
    m = np.max(np.abs(x)) or 1
    return x / m * peak


def synth(name: str) -> np.ndarray:
    t = lambda s: np.arange(int(SR * s)) / SR  # noqa: E731
    if name == "whoosh":          # light whoosh / transition
        n = int(SR * 0.45)
        x = _bandsweep(_noise(n, 1), 300, 6000)
        e = np.sin(np.linspace(0, np.pi, n)) ** 2
        return _norm(x * e, 0.7)
    if name == "whoosh_heavy":
        n = int(SR * 0.7)
        x = _bandsweep(_noise(n, 2), 120, 3500) + 0.3 * np.sin(2 * np.pi * np.geomspace(60, 180, n) * t(0.7))
        e = np.sin(np.linspace(0, np.pi, n)) ** 1.5
        return _norm(x * e, 0.85)
    if name == "whip":
        n = int(SR * 0.18)
        x = _bandsweep(_noise(n, 3), 2000, 9000)
        return _norm(x * _env(n, 0.01, 22), 0.6)
    if name == "riser":            # 1.2 s build, ends exactly at the impact
        d = 1.2
        n = int(SR * d)
        f = np.geomspace(180, 1400, n)
        tone = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.4 * np.sin(4 * np.pi * np.cumsum(f) / SR)
        x = 0.6 * tone + 0.6 * _bandsweep(_noise(n, 4), 400, 9000)
        e = np.linspace(0, 1, n) ** 2.2
        return _norm(x * e, 0.7)
    if name in ("boom", "impact"):
        tt = t(1.3)
        f = 70 - 40 * np.clip(tt, 0, 1)
        x = 0.95 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-3.2 * tt)
        x += 0.35 * _noise(len(tt), 5) * np.exp(-16 * tt)
        return _norm(x, 0.95)
    if name == "hit":              # punchy short hit
        tt = t(0.35)
        f = 160 * np.exp(-tt * 18) + 50
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-9 * tt) + 0.5 * _noise(len(tt), 6) * np.exp(-40 * tt)
        return _norm(x, 0.9)
    if name == "pop":
        tt = t(0.16)
        x = np.sin(2 * np.pi * (1200 - 900 * tt) * tt) * np.exp(-30 * tt)
        return _norm(x, 0.7)
    if name == "click":
        tt = t(0.04)
        x = _noise(len(tt), 7) * np.exp(-140 * tt) + np.sin(2 * np.pi * 3000 * tt) * np.exp(-90 * tt)
        return _norm(x, 0.5)
    if name == "ding":
        tt = t(1.4)
        x = sum(a * np.sin(2 * np.pi * f * tt) for f, a in [(1760, 1), (3520, .35), (5280, .15), (2637, .25)])
        return _norm(x * np.exp(-3 * tt) * _env(len(tt), 0.002), 0.55)
    if name == "bass_drop":
        tt = t(1.1)
        f = np.geomspace(140, 38, len(tt))
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-1.8 * tt)
        return _norm(x, 0.95)
    if name == "scratch":          # record-scratch style stop (awkward moment)
        tt = t(0.5)
        f = 900 * np.sin(2 * np.pi * 6 * tt) ** 2 + 120
        x = 0.6 * _bandsweep(_noise(len(tt), 8), 600, 3000) * np.sin(2 * np.pi * np.cumsum(f) / SR)
        return _norm(x * np.exp(-3 * tt), 0.6)
    if name == "shutter":
        a = synth("click")
        return np.concatenate([a, np.zeros(int(SR * 0.06)), a * 0.8])
    raise KeyError(name)


SFX_NAMES = ["whoosh", "whoosh_heavy", "whip", "riser", "boom", "hit", "pop", "click", "ding", "bass_drop",
             "scratch", "shutter"]


def write_wav(path: Path, x: np.ndarray, sr: int = SR):
    path.parent.mkdir(parents=True, exist_ok=True)
    st = np.stack([x, x], axis=1) if x.ndim == 1 else x
    pcm = (np.clip(st, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def sfx(name: str) -> Path:
    custom = ASSETS / "sfx" / f"{name}.wav"
    if custom.exists():
        return custom
    p = CACHE / f"v2_{name}.wav"
    if not p.exists():
        write_wav(p, synth(name))
    return p


# ------------------------------------------------------------------ original beat loops (music bed)
def _kick(n):
    tt = np.arange(n) / SR
    return np.sin(2 * np.pi * np.cumsum(150 * np.exp(-tt * 25) + 45) / SR) * np.exp(-7 * tt)


def _snare(n, seed):
    tt = np.arange(n) / SR
    return (0.7 * _noise(n, seed) + 0.4 * np.sin(2 * np.pi * 190 * tt)) * np.exp(-18 * tt)


def _hat(n, seed):
    x = np.diff(_noise(n + 1, seed))
    return x * np.exp(-60 * np.arange(n) / SR) * 0.35


BEATS = {
    # name: (bpm, 808 note pattern in Hz per beat, swing)
    "phonk": (130, [49, 49, 55, 41.2], 0.0),
    "trap": (140, [43.65, 43.65, 51.9, 38.9], 0.0),
    "chill": (92, [55, 65.4, 49, 61.7], 0.08),
}


def beat(name: str = "phonk", bars: int = 8) -> Path:
    """Synthesize an original drum + 808 loop (licence-free music bed)."""
    custom_dir = ASSETS / "music"
    p = MUSIC_CACHE / f"{name}.wav"
    if p.exists():
        return p
    bpm, notes, swing = BEATS.get(name, BEATS["phonk"])
    spb = 60 / bpm
    n_total = int(SR * spb * 4 * bars)
    mix = np.zeros(n_total)
    step = spb / 4  # 16th notes
    for i in range(bars * 16):
        st = int(SR * (i * step + (swing * step if i % 2 else 0)))
        if st >= n_total:
            break
        beat_i = i // 4
        # kick on 1 and the "and" of 2, snare on 2 & 4, hats every 8th (16ths on bar ends)
        if i % 16 in (0, 6, 10):
            k = _kick(int(SR * 0.4))
            mix[st:st + len(k)] += k[: n_total - st] * 0.9
        if i % 8 == 4:
            s = _snare(int(SR * 0.25), i)
            mix[st:st + len(s)] += s[: n_total - st] * 0.55
        if i % 2 == 0 or (i % 16) >= 14:
            h = _hat(int(SR * 0.06), i)
            mix[st:st + len(h)] += h[: n_total - st]
        if i % 4 == 0:  # 808 note per beat
            f = notes[(beat_i // 1) % len(notes)]
            ln = int(SR * spb * 0.95)
            tt = np.arange(ln) / SR
            b8 = np.tanh(2.5 * np.sin(2 * np.pi * f * tt)) * np.exp(-1.6 * tt) * 0.5
            mix[st:st + ln] += b8[: n_total - st]
    _ = custom_dir
    return write_wav(p, _norm(mix, 0.8))


def plan(dur: float, *, hook: bool, hook_secs: float, punches: list[float], zoom_bounds: list[float],
         hook_at: float = 0.0,
         emojis: list[float], actions: list[float], cta: bool, level: str = "auto") -> list[tuple[str, float, float]]:
    """Return [(sfx_name, start_time, volume)] following viral-edit conventions."""
    if level in ("off", "none", None):
        return []
    out = []
    if hook:
        out += [("whoosh_heavy", max(0.0, hook_at - 0.15), 0.7), ("hit", hook_at + 0.05, 0.55)]
        if hook_secs and hook_at + hook_secs < dur:
            out.append(("click", hook_at + hook_secs, 0.45))
    for p in punches:
        out.append(("riser", max(0.0, p - 1.2), 0.45))
        out.append(("boom", max(0.0, p - 0.02), 1.0))
        out.append(("whip", p + 0.05, 0.5))
    if level == "auto":
        for b in zoom_bounds:
            if all(abs(b - p) > 1.0 for p in punches):
                out.append(("whip", max(0.0, b - 0.08), 0.28))
        for e in emojis:
            if all(abs(e - p) > 0.3 for p in punches):
                out.append(("pop", e, 0.5))
        for a in actions:
            out.append(("hit", a, 0.5))
    if cta:
        out.append(("ding", max(0.0, dur - 2.0), 0.45))
    return [(n, round(t, 3), v) for n, t, v in out if t < dur]
