# Per-platform personalisation

Write each platform's copy separately — same clip, different audience and UI. `clipstudio check` enforces the limits.

| platform | max length | text limit | hashtags | voice |
|---|---|---|---|---|
| YouTube Shorts | 3 min | title 100, desc 5000, tags 500 chars | 2–4 + `#Shorts` | searchable: name the game, character, streamer, moment |
| TikTok | 10 min (aim < 60 s) | 2200 | 3–5 | casual, lowercase ok, end with a question |
| Instagram Reels | 3 min (aim < 60 s) | 2200 | 3–5 at the end | hook line, context, credit, CTA (follow/save/share) |
| Facebook Reels | 90 s | 2200 | 2–3 | plain description, slightly older audience |
| X | 140 s | 280 | 1–2 | one punchy line + credit handle |

## YouTube Shorts
- Title = the hook as a curiosity gap, ideally ≤ 60 chars so it is not cut off; 0–1 emoji.
- Description: 1–2 lines of context, the credit line, then `#Shorts #GTA6 #<streamer>`.
- Tags: `gta 6`, `gta vi`, `vice city`, streamer name, character names, the mission/moment.
- Category 20 (Gaming). Not made for kids.

## TikTok
- First line = hook (it shows over the video). Then a question: "would you have taken the deal?"
- Hashtags: one broad (#gaming / #fyp is optional), two niche (#gta6 #vicecity), one streamer tag.

## Instagram Reels
- Line 1 hook, line 2 context ("GTA 6 day one with ___"), line 3 credit, line 4 CTA, hashtags last.
- Use `cover.jpg` as the cover so the grid looks clean.

## X
- ≤ 240 chars. A reaction, not a description. Tag the streamer's X handle if known.

## Timing
Default slots are in `[schedule]` of the config (local time zone from `[post].timezone`). Space clips ≥ 2 h apart per
platform. On launch day / big streams, post live-mode clips immediately — speed beats polish.

## Languages
Non-English GTA pages are much less crowded. A clip with translated captions + a translated hook/post in es/pt/de/fr
can be queued to separate language accounts.
