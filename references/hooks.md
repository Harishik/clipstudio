# Hooks, titles and post captions

Built from the titles and first frames of shorts with **2M to 1.1B views** (MrBeast, IShowSpeed, Sidemen, Zach King,
Kai Cenat's clip channel) plus short-form hook research. The first 1.5–3 seconds decide whether anyone sees the rest.

## Workflow per clip
1. `clipstudio hooks <job> <clip>` gives you the transcript, **chat at that exact moment**, **comments that
   timestamped it** (with likes), the formulas below and the rules.
2. Write **3 on-screen hooks**, each with a different formula (curiosity / stakes / reaction).
3. `clipstudio hookcheck "hook 1" "hook 2" "hook 3"` scores each one (0–100) with fixes. Keep the best (≥ 80).
4. Render: `--hook "…"` (wrap the key word in `*stars*`, at most one emoji). Optionally add `--tease` to flash the payoff first.
5. Write the post title and captions (below). Check titles with `clipstudio hookcheck --kind title "…"`.

## On-screen hook formulas (≤ 8 words)
| formula | how | real examples |
|---|---|---|
| question | ask what they'll stay to see answered | "HOW MANY 🥑 ARE HIDDEN ON HIM?" · "Which one is cake? 🍰" |
| consequence | something happens, don't say what | "He didn't see the cars coming" · "He thought he was safe…" |
| superlative | worst / fastest / first / biggest | "World's fastest date" · "Worst landing in GTA 6" |
| challenge | stakes plus a number | "Hit the button, win $1,000" |
| POV | put the viewer inside it | "POV: you trusted your friend to fly" |
| wait | promise a payoff | "Wait for the ending 💀" · "Watch his face at the end" |
| reaction | the reaction is the hook | "Chat called this a *W* landing 💀" |
| callout | speak to a group | "Only real GTA fans noticed this" |

**Rules**
- Specific nouns: names, numbers, objects.
- Open a loop the clip closes. Never spoil the payoff, never lie.
- On-screen text, first spoken line and post title all point at the same gap.
- At most one emoji, and it can replace a word.
- The audience's own words make the best hooks: chat lines like "W landing" or "flight sim guy" are gold.

**On-screen styles** (`--headline-style`)
- `auto` (default): on the seam for facecam layouts. Otherwise a persistent yellow question at the top
  (Sidemen style) that stays until the payoff when `--hook-secs 0` is set.
- `top`: forces the yellow top question.
- `box`: classic white box.

Every style reveals word by word (about 0.07 s per word), with a whoosh and a hit on entry.

**Cold open** (`--tease ["TEXT"]`): the first 1.5 s show the payoff with "WAIT FOR IT 👀", then the clip plays from
the start with the hook. It's the strongest retention trick for clips where the payoff comes late.

## Post titles (what the top clip channels actually write)
| formula | pattern | real examples |
|---|---|---|
| name does | [Name] [does / can't believe / finds] [specific thing] + 1–2 emoji | "Kai Cenat Can't Believe How Much This Girl Charges 😂" · "Kai Cenat Finds A Japanese Fanum! 💀😭" |
| question + one caps word | | "He hid the last avocado WHERE?!" · "Who can score all three?" |
| superlative | | "Who's The Strongest Streamer?" · "World's Fastest Date" |
| consequence | | "He didn't see the cars coming" · "iShowSpeed Gets A Job at KFC!" |

Use present tense, and third person when clipping someone else. Keep it ≤ 60 characters (YouTube cuts the feed there).
Caps on ONE word, never the whole title. Put emoji at the end.

## Post captions (description / caption body)
```
<hook line, reworded for the platform>
<one line of context: who, where — "GTA 6 day 2 with ZerkaaPlays">
🎥 Credit: <creator> (<link/handle>)
<comment-bait question: "Would you have landed it better? 😭" / "Rate this landing 1-10">
#gta6 #<niche> #<creator> #gaming
```
- **YouTube:** title from the table above. Description is the caption body plus `#Shorts`. Tags: game, creator, moment.
- **TikTok:** lowercase-casual first line, the question, 3–5 hashtags (1 broad, 2 niche, 1 creator).
- **Instagram:** hook, context, credit, "Follow for part 2 / save this", 3–5 hashtags at the end.
- **X:** one punchy reaction line plus credit, under 240 characters.
- **Facebook:** a plain description of what happens, 2–3 hashtags.

Never use: "you won't believe", "gone wrong", "not clickbait", leaks, "free download", fake news, or impersonating
the creator.
