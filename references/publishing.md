# Publishing & daily automation (100% free, no API keys)

Fetching (live, VODs, videos, chat, comments) never needs an account. **Posting** goes to your own accounts through
your own browser session. No Google Cloud project, no API keys, no paid schedulers.

## 1. Sign in once per platform
```bash
clipstudio login youtube      # also: tiktok, instagram, x
```
A Chrome window opens on the platform's sign-in page, using a dedicated profile in `~/.clipstudio/browser-profile`.
You sign in yourself (ClipStudio never sees or stores your password), then close the window. Sessions last weeks;
run `login` again if a post fails with "not signed in".

## 2. Queue → approve → publish
- `clipstudio queue <job> <clip> --platforms youtube,tiktok,instagram` gives each platform the next free slot from
  `[schedule]` in the config.
- `clipstudio approve <id|all>` (skipped automatically if `[post] auto_post = true`).
- `clipstudio publish` posts every approved item that is due: YouTube Studio upload (title, description, not-for-kids,
  Public), TikTok Studio, Instagram Reels, X. `--now` ignores the slot time; `--headless` hides the window.
- Not supported or failed? The clip is exported to `~/ClipStudio/outbox/<platform>-<id>/` (video, cover, caption.txt)
  and the error and a screenshot are saved next to the clip.
- Web UIs change. If a flow breaks, the screenshot shows where; the selectors live in `scripts/cs/browser_post.py`.
- Personal use: browser automation of your own account is the free route, but keep volumes human (a few posts per day
  per platform) to stay within each platform's rules.

## 3. Run it every day automatically
`clipstudio daily` is the autopilot. It records whoever is live (your `[daily] channels` first, else the biggest
streams for the game), auto-clips chat/audio spikes, processes the day's most-viewed new YouTube videos for
`video_query`, and renders drafts. An agent then judges the drafts, writes the hooks and per-platform posts,
re-renders, checks and queues. The full instructions are in **`prompts/daily-task.md`**.

Run it from your agent's scheduler (prompt = contents of `prompts/daily-task.md`):

| Agent | How |
|---|---|
| **Claude desktop app (Code tab)** | Ask Claude: *"schedule the clipstudio daily task every day at 7pm"*. It creates a local scheduled task (runs while the app is open, catches up on next launch). |
| **Claude Code CLI** | cron: `0 19 * * * cd ~ && claude -p "$(cat ~/.clipstudio/app/prompts/daily-task.md)" --permission-mode bypassPermissions >> ~/ClipStudio/daily.log 2>&1` |
| **Codex** | Codex app → Automations → new daily automation with the prompt; or cron: `codex exec --full-auto "$(cat …/prompts/daily-task.md)"` |
| **Gemini CLI / Antigravity** | cron: `gemini -p "$(cat …/prompts/daily-task.md)" --yolo`; Antigravity: paste the prompt into a scheduled agent task. |
| **ChatGPT** | ChatGPT Tasks cannot run programs on your computer. Use Codex, which can. |
| **No agent at all** | cron: `0 19 * * * clipstudio daily --auto-copy --publish` (template hooks, so lower quality than an agent). |

Extra cron line so later slots also go out: `*/30 * * * * clipstudio publish --headless`.

Pick the run time when your streamers are usually live (often evening in their time zone). `live_minutes` sets how long
it watches.
