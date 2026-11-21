---
name: clipstudio
description: Free, no-login clipping studio for Twitch and YouTube (GTA 6 or any game). Clips live streams as they happen, finished streams/VODs, and ANY YouTube video (gameplay, walkthroughs, funny moments, 5 min to 10 h). Finds viral moments from chat spikes, timestamped comments, on-screen action, loudness and speech; edits top-tier vertical shorts (facecam split, pop captions, hook, zoom/shake/flash impacts, SFX, dead-air cuts, -14 LUFS); writes per-platform posts; schedules and posts through the user's own browser session; runs as a daily autopilot. Use for "clip this stream/video", "clip streamers live", "find viral GTA 6 videos to clip", "post/schedule my clips", "run my daily clipping".
---

# ClipStudio

**find → fetch (no login) → score → judge → cut → edit → write posts → check → schedule → post → learn**
Everything is free: no API keys, no paid services. Every command prints JSON.
Run `clipstudio <cmd>`; if not on PATH: `python3 <this skill's folder>/scripts/clipstudio.py <cmd>`.
New machine: `clipstudio doctor` → if anything is missing `bash <skill folder>/install.sh --deps-only` → `clipstudio setup`.

**Quality bar: every clip should look like it came from a top clip channel with millions of views.** Judge every
moment and every render with your own eyes (open the images). A loud moment isn't automatically a good one. Never ship a draft you haven't looked at.

## Step 0: basis
Record why clipping is OK with `--basis`: `campaign` (pass `--campaign rules.json`, see `examples/`), `permission`
(note where the creator allowed it), `own`, or `transformative` (commentary/ranking/story added). Saved to
`PERMISSION.md`. Read `references/rules.md` once per session. For unattended daily runs the configured default is used.

## Ask the user's choices first (short, one message)
Unless they already said: **how many clips** (any number), target length (15/30/45/60 s), caption style (`auto` default = best per clip;
show `clipstudio styles <job> <clip>` if they want to pick), and platforms. Then respect them exactly.
One command does the bulk: `clipstudio make <url> --clips N --length S --style X [--layout auto|track|facecam|blur|fill]`.
Afterwards you still judge, write hooks, and re-render each clip (steps 3–9 below).

## Step 1: pick sources (all three kinds)
- Live now: `clipstudio streams --game "gta 6" [--lang en]` (Twitch + YouTube by viewers)
- Any YouTube video: `clipstudio videos --query "GTA 6 funny moments" --min 5 --max 120 --days 7 --sort views`
  (gameplay, walkthroughs, compilations, finished streams; filter by length and recency)
- Trending: `clipstudio trends --query "GTA 6" --hours 24` (views per hour)
- A channel's past streams: `clipstudio vods <channel url>`

## Recorded or any video
1. `clipstudio new <url> --basis <basis>` → `job`.
2. `clipstudio moments <job> --count 8 --length 30`. Downloads audio only and scores every second using:
   - chat replay (YouTube, and Twitch when allowed);
   - timestamps in the top comments (people write "4:32 LMAO"), weighted by likes;
   - on-screen action from a tiny 144p pass (motion and hard cuts; automatic when there is no chat);
   - loudness, and YouTube "most replayed" data when YouTube provides it.
   Add `--speech` for commentary-heavy videos. Chat-driven windows are shifted earlier automatically, because chat
   reacts 5–15 s after the moment.
3. Judge: `clipstudio inspect <job> --ids 1,2,...`. Open every `preview` image and read `said`, `chat` and the
   comments. Reject menus, pause/loading screens, talking with no action, ads, BRB, and moments that need long context.
   Reject anything that only works with an offensive framing (comments joking about real tragedies, slurs). If the
   payoff sits outside the window, grab frames around it (`clipstudio frame`) and pick exact times.
4. `clipstudio cut <job> --moment N` or `--start S --end E` (cuts only those seconds from the source). Aim for 15–45 s,
   with the first second already interesting.
5. Captions are auto-transcribed. For non-English speech and an English audience: `clipstudio transcribe <job> <clip> --translate`.
   Source already has burned-in captions (an edited compilation)? Render with `--style none`.
6. Render (defaults are the viral style; see `references/editing.md`). Caption `--style`: auto (default; picks
   per clip from pace, energy, layout and amount of speech, and prints why) | stream | hormozi | beast | box |
   karaoke | spotlight | neon | minimal. Respect the user's choice if they named one. Layout `track` = auto-reframe that follows
   the speaker (talking/IRL footage). Add action captions by inserting `{"w": "*LAUGHS*", "s": .., "e": ..}` into
   `words.json` where something happens without speech.
   `clipstudio render <job> <clip> --hook "He landed the plane *ON* his truck 💀" --title "Worst landing" --punch 15 --emoji 💀`
   - Layout `auto`: facecam split when a webcam overlay is found (it snaps to the overlay's border and crops around
     the face), else `blur`. `--layout fill --focus 0..1` for centered action. Override the cam with `--facecam x,y,w,h`.
   - Dead air is removed automatically. Impacts come from `--punch <sec>` (zoom + shake + flash + boom + emoji);
     automatic detection only fires on sharp sound jumps, so give the real impact second when you know it.
   - `--music auto` (royalty-free tracks in assets/music), `--cta "Part 2?"`, `--trim s,e`, `--cap-size 70`.
6b. Hooks & sound (see `references/hooks.md`):
   - `clipstudio hooks <job> <clip>` gives you the transcript, chat and comments from that exact moment, plus formulas.
   - Write 3 hooks with different formulas, then `clipstudio hookcheck "…" "…" "…"` and keep one scoring 80+.
   - Use `--tease` when the payoff comes late, and `--music phonk|trap|chill` (original beats).
   - SFX are automatic: whoosh+hit on the hook, riser→boom on impacts, whips on zoom cuts, pops, ding on the CTA.
   - Use `--hook-secs 0` to keep a question hook on screen until the payoff.
7. Look at the render (5–6 frames at different times, including one at the punch). Check that:
   - no text covers the face;
   - captions are readable and not oversized;
   - the headline is legible;
   - the impact lands on the action.
   Fix it and render again if needed.
8. `clipstudio posts <job> <clip> --platforms youtube,tiktok,instagram,x` → fill `post.json`. It already contains the
   audience reactions and title formulas. Titles follow the patterns of top clip channels ("[Name] can't believe
   [specific] 😂", "He did WHAT?!", ≤ 60 chars). Each caption has the hook line, context, credit, a comment-bait
   question and 3–5 tags. See `references/hooks.md` and `references/platforms.md`. `check` warns on weak hooks/titles.
9. `clipstudio check <job> <clip>` must be ok → `clipstudio queue <job> <clip> --platforms ...`.

## Live (be first)
`clipstudio live <twitch|youtube url> --basis <basis> --auto-render` (run in the background and watch stdout).
- Records with streamlink into a rolling buffer.
- Reads chat anonymously: Twitch IRC, and YouTube's full "Live chat" (not "Top chat").
- Detects chat and audio spikes and saves `CLIP NN saved -> raw.mp4` with a captioned draft.
- For each `CLIP` line, judge it, then continue from step 5. Tune with `--mult --min-msgs --pre --post --cooldown`.
- Chat-quiet streams fall back to audio spikes.

## Posting (free, through the user's browser)
- One-time per platform: `clipstudio login youtube|tiktok|instagram|x`. The user signs in themselves in the ClipStudio
  Chrome profile. Never ask for or type their password.
- `clipstudio approve <ids|all>` (unless `auto_post = true`) → `clipstudio publish` posts everything approved and due
  (YouTube Studio, TikTok Studio, Instagram, X). Failures get exported to `~/ClipStudio/outbox` with a screenshot.
- Never post without approval unless the user turned on `auto_post`.
- Details: `references/publishing.md`.

## Daily autopilot
`clipstudio daily [--clips N]` records live streams (the `[daily] channels` first) and processes the day's top new videos into
drafts, writing `~/ClipStudio/daily/<date>.json`. A scheduled agent then follows `prompts/daily-task.md`: judge, re-cut,
hook, re-render, posts, check, queue, publish. To set this up for the user, create a daily scheduled task whose prompt
is the content of `prompts/daily-task.md`, at the time their streamers are usually live. Other agents and cron:
`references/publishing.md`. With no agent: `clipstudio daily --auto-copy --publish` (template hooks).

## Learn
`clipstudio stats` refreshes public view counts in `scoreboard.csv`. Tell the user which hooks, layouts and times work,
and change one thing per day.

## Hard rules
No leaks, no "play early"/"free download"/cracks, no GTA Online money/mod-menu/AFK-bot content, no fake news, never
impersonate Rockstar or the streamer, always credit the source (unless `own`), follow campaign rules, and keep
posting volumes human.

## Files
`~/ClipStudio/jobs/<job>/`: `job.json`, `PERMISSION.md`, `audio.m4a`, `chat.jsonl`, `comments.json`, `moments.json`,
`previews/`, `clips/NN/{raw.mp4, words.json, final.mp4, cover.jpg, post.json, check.json}`. Queue:
`~/ClipStudio/queue.json`. Config: `~/.clipstudio/config.toml`.
