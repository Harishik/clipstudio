# ClipStudio — instructions for coding agents (Codex, Antigravity, Gemini, OpenCode, Cursor, Copilot…)

This repository is an agent skill + CLI that clips **live streams, finished streams and any YouTube video** (Twitch +
YouTube) into top-tier vertical shorts, writes per-platform posts, rule-checks them and schedules/posts them through the
user's own browser session. 100% free: no login to fetch, no API keys to post.

- The complete workflow, rules and command reference is in **[SKILL.md](SKILL.md)** — read it fully before acting.
- Style and platform guides: `references/editing.md`, `references/platforms.md`, `references/publishing.md`,
  `references/rules.md`.
- CLI: `clipstudio <command>` (installed by `install.sh`) or `python3 scripts/clipstudio.py <command>`. Every command
  prints JSON on stdout; progress goes to stderr.
- Setup on a new machine: `bash install.sh --deps-only` (needs ffmpeg + Python 3.10+), then `clipstudio doctor`.

Agent-specific notes:
- You must **look at images** (`previews/mNN.jpg`, frames of `final.mp4`) before deciding what to cut or post. If your
  agent cannot view images, rely on `said`/`chat` text from `inspect` and tell the user to review visually.
- Long-running live mode: start `clipstudio live <url> ...` as a background process and poll its stdout for
  `CLIP NN saved` lines.
- Never post without explicit user approval unless `auto_post = true` in `~/.clipstudio/config.toml`.
- Never ask for, type or store passwords. Posting uses a browser profile the user signed into themselves (`clipstudio login <platform>`).
- Daily autopilot: schedule a daily task with the prompt in `prompts/daily-task.md` (see `references/publishing.md`).

Code layout: `scripts/clipstudio.py` (CLI) → `scripts/cs/` modules: `discover` (live, trending, any-video search), `fetch` (no-login
metadata, audio-only, remote section cuts, frames), `twitch` (anonymous VOD resolver), `chat` (anonymous Twitch IRC,
YouTube live/replay chat, Twitch VOD chat), `score` (chat, comment timestamps, loudness, on-screen action, speech → peaks), `live` (record + spike
clipping), `transcribe` (faster-whisper words), `facecam` (webcam finder), `render` (1080×1920 editor, Pillow overlays,
ffmpeg graph, -14 LUFS), `posts` (platform specs + checks), `publish` (queue, approval, export, stats), `browser_post` (free posting via Playwright + your Chrome profile),
`daily` (autopilot).
