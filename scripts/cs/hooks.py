"""Hook + post-copy engine: context pack, proven formulas, and a scorer.

Formulas come from (a) the titles/on-screen hooks of shorts with 2M-1.1B views (MrBeast, IShowSpeed, Sidemen,
Zach King, Kai Cenat's clip channel) and (b) short-form hook research (the first 1.5-3 s decide retention).
The agent writes the actual lines — this module gives it the raw material and checks the result.
"""
from __future__ import annotations

import re
from pathlib import Path

from .util import read_json

# ---------------------------------------------------------------- formulas (with real examples)
ON_SCREEN = [  # <= 8 words, shown in the first frame, mirrors the moment
    ("question", "Ask the thing they'll stay to see answered", ["HOW MANY 🥑 ARE HIDDEN ON HIM?", "Who's the strongest streamer?",
                                                                "Which one is cake? 🍰"]),
    ("consequence", "Tell them something happens, not what", ["He didn't see the cars coming", "This did NOT go to plan",
                                                              "He thought he was safe…"]),
    ("superlative", "Biggest / worst / fastest / first", ["World's fastest date", "Worst landing in GTA 6",
                                                          "First day at KFC"]),
    ("challenge", "Stakes + a number", ["Hit the button, win $1,000", "Survive 100 hours in GTA 6"]),
    ("pov", "Put the viewer in it", ["POV: you trusted your friend to fly", "POV: your first GTA 6 heist"]),
    ("wait", "Promise a payoff", ["Wait for the ending 💀", "Watch his face at the end"]),
    ("reaction", "The reaction is the hook", ["Chat lost it at this 😭", "His reaction says everything"]),
    ("callout", "Talk to a group", ["Only real GTA fans noticed this", "If you've played GTA, you know"]),
]

POST_TITLE = [  # how the top clip channels title/caption the post itself
    ("name_does", "[Name] [does/can't believe/finds] [specific thing] [emoji]",
     ["Kai Cenat Can't Believe How Much This Girl Charges 😂", "Kai Cenat Finds A Japanese Fanum! 💀😭",
      "Fanum Is Worried He Would Have To Skip Thanksgiving To Play GTA VI 😂"]),
    ("question_caps", "Question with ONE word in caps", ["He hid the last avocado WHERE?!", "Who can score all three?"]),
    ("superlative", "Superlative / record", ["Who's The Strongest Streamer?", "LIFTING THE HEAVIEST BLOCK IN THE WORLD"]),
    ("consequence", "Consequence, no spoiler", ["He didn't see the cars coming", "iShowSpeed Gets A Job at KFC!"]),
]

RULES = [
    "On-screen hook: <= 8 words, lands in the first 1.5 s, one focal idea, specific nouns (names, numbers, objects).",
    "Open a loop the clip closes; never spoil the payoff; never lie (clickbait that doesn't pay off kills retention).",
    "Mirror the hook: on-screen text, the first spoken line and the post title should all point at the same gap.",
    "One emoji max on screen; it can replace a word (HOW MANY 🥑 …). 1-2 emoji at the END of a post title.",
    "Write 3 hooks per clip using different formulas (curiosity / stakes / reaction), pick the strongest, keep the "
    "others for other platforms or A/B tests.",
    "Use the audience's own words: chat lines and timestamped comments about this moment are the best hook material.",
    "Post title: <= 60 chars for YouTube (fits the feed), present tense, third person for clips of others.",
    "Post caption: first line repeats the hook, then 1 line of context, credit, then a comment-bait question, 3-5 tags.",
]

CLICKBAIT = re.compile(r"\b(you won'?t believe|gone wrong|not clickbait|must watch|shocking|insane!!+)\b", re.I)
WEAK_START = re.compile(r"^(so|in this video|today|hey guys|this is a video|check out)\b", re.I)
CURIOSITY = re.compile(r"(\?|…|\.\.\.|\bwhy\b|\bhow\b|\bwhat\b|\bwho\b|\bwait\b|\bnobody\b|\bonly\b|\bthis\b|"
                       r"\bdidn'?t\b|\bnot\b|\bnever\b|\bfirst\b|\bworst\b|\bbest\b|\bpov\b|\bwhen\b|\d)", re.I)


def score(text: str, kind: str = "hook") -> dict:
    """Quick quality check for an on-screen hook or a post title. 0-100 + concrete tips."""
    t = (text or "").replace("*", "").strip()
    words = re.findall(r"[\w'’$]+", t)
    tips, s = [], 100
    limit = 8 if kind == "hook" else 12
    if not t:
        return {"score": 0, "tips": ["empty"]}
    if len(words) > limit:
        s -= 10 * (len(words) - limit)
        tips.append(f"{len(words)} words — cut to <= {limit}")
    if kind == "title" and len(t) > 60:
        s -= 15
        tips.append(f"{len(t)} chars — YouTube cuts titles around 60 in the feed")
    caps_emphasis = bool(re.search(r"\b[A-Z]{2,}\b", t)) and not t.isupper()
    if not CURIOSITY.search(t) and not caps_emphasis:
        s -= 20
        tips.append("no curiosity/stakes cue (question, number, 'didn't', 'worst', 'wait', 'this'…)")
    if WEAK_START.search(t):
        s -= 20
        tips.append("weak opener — start with the subject or the twist")
    if CLICKBAIT.search(t):
        s -= 25
        tips.append("generic clickbait phrase — be specific instead")
    emo = re.findall("[\U0001F300-\U0001FAFF☀-➿]", t)
    if kind == "hook" and len(emo) > 1:
        s -= 10
        tips.append("more than one emoji on screen")
    if t.isupper() and len(words) > 3 and kind == "title":
        s -= 10
        tips.append("all caps title reads as spam — caps on ONE word")
    if not re.search(r"[A-Z][a-z]+|\d", t) and kind == "title":
        tips.append("add a specific name or number")
    return {"score": max(0, s), "tips": tips or ["looks strong"]}


def context(job: Path, clip_dir: Path) -> dict:
    """Everything an agent needs to write killer hooks for one clip."""
    from . import chat as chatmod
    j = read_json(job / "job.json") or {}
    meta = read_json(clip_dir / "clip.json") or {}
    words = (read_json(clip_dir / "words.json") or {}).get("text", "")
    a, b = meta.get("start", 0), meta.get("end", 0)
    chat_lines = [r["text"] for r in chatmod.load(job) if a - 2 <= r["t"] <= b + 15][:60]
    comments = []
    for c in read_json(job / "comments.json", []) or []:
        for h, m, s_ in re.findall(r"(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)", c["text"]):
            ts = int(h or 0) * 3600 + int(m) * 60 + int(s_)
            if a - 5 <= ts <= b + 5:
                comments.append({"likes": c.get("likes", 0), "text": c["text"][:200]})
                break
    comments.sort(key=lambda c: -c["likes"])
    return {
        "source_title": j.get("title"), "channel": j.get("channel"), "transcript": words[:1500],
        "chat_at_this_moment": chat_lines, "comments_about_this_moment": comments[:15],
        "on_screen_formulas": [{"name": n, "how": h, "examples": e} for n, h, e in ON_SCREEN],
        "post_title_formulas": [{"name": n, "how": h, "examples": e} for n, h, e in POST_TITLE],
        "rules": RULES,
        "next": "write 3 on-screen hooks (different formulas) + a post title per platform; check them with "
                "`clipstudio hookcheck \"...\"`; render with --hook; fill post.json",
    }
