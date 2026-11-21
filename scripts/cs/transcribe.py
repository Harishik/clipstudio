"""Speech-to-text with word timestamps (faster-whisper, runs locally, free)."""
from __future__ import annotations

import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from .util import load_config, log


@lru_cache(maxsize=2)
def _model(name: str):
    from faster_whisper import WhisperModel
    try:
        import torch  # noqa: F401
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        dev = "cpu"
    return WhisperModel(name, device=dev, compute_type="int8" if dev == "cpu" else "float16")


def words(media: Path, start: float | None = None, end: float | None = None,
          language: str | None = None, model: str | None = None, translate: bool = False) -> dict:
    cfg = load_config()
    model = model or cfg.get("whisper_model", "small")
    src = Path(media)
    tmp = None
    if start is not None:
        tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(src)]
        if end is not None:
            cmd += ["-t", str(end - start)]
        subprocess.run(cmd + ["-ac", "1", "-ar", "16000", str(tmp)], check=True)
        src = tmp
    log(f"transcribing with whisper-{model}...")
    language = language or cfg.get("language")
    segs, info = _model(model).transcribe(str(src), word_timestamps=True, vad_filter=True,
                                          task="translate" if translate else "transcribe",
                                          language=None if language in (None, "", "auto") else language)
    out = []
    for s in segs:
        for w in s.words or []:
            t = w.word.strip()
            if t:
                out.append({"w": t, "s": round(w.start, 2), "e": round(w.end, 2)})
    if tmp:
        tmp.unlink(missing_ok=True)
    return {"language": info.language, "words": out, "text": " ".join(w["w"] for w in out)}
