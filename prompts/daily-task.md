You are running the ClipStudio daily autopilot (skill: clipstudio). Goal: post-ready VIRAL vertical clips from today's
GTA 6 (or configured game) streams and videos, edited to top clip-channel standard. Work without asking questions;
the user set this up to run unattended. Use `clipstudio <cmd>` (or `python3 <skill folder>/scripts/clipstudio.py`).

1. `clipstudio doctor` — if something is missing, run the skill's `install.sh --deps-only` once.
2. `clipstudio daily` (add `--clips N` if the user chose a number) — records the live streams (preferred channels first) and processes today's top new videos.
   It prints a report with every draft (`drafts[]`: job, clip, video, transcript). This takes ~live_minutes.
3. For EACH draft (be ruthless — only real viral moments survive):
   a. Extract 6 frames across `final.mp4` (`ffmpeg -ss T -i final.mp4 -frames:v 1 fN.jpg`) and LOOK at them, read the
      transcript. Reject: menus, loading/pause screens, talking with no game action, nothing happening, unclear context,
      anything needing a sensitive/offensive framing. Keep at most the number of clips the user configured (`[daily] clips_per_source`), and fewer if they aren't good enough.
   b. For keepers decide the exact payoff second; if the moment starts late/early re-cut with
      `clipstudio cut <job> --start <s> --end <e> --id <clip>` (15–45 s, first second already interesting).
   c. `clipstudio hooks <job> <clip>` (chat + comments at that moment, formulas). Write 3 hooks with different
      formulas, `clipstudio hookcheck` them, and keep one scoring 80+. Add a 2–4 word title. Re-render:
      `clipstudio render <job> <clip> --hook "..." --title "..." --punch <impact second> --emoji <emoji> --music phonk`
      (add `--tease` when the payoff comes late; `--hook-secs 0` keeps a question hook on screen).
      (add `--style none` if the source already has burned-in captions; `--layout blur` if no webcam).
   d. Look at 4 frames of the new `final.mp4`: face not covered, captions readable and not huge, headline legible,
      nothing important hidden. Fix and re-render if not.
   e. `clipstudio posts <job> <clip> --platforms youtube,tiktok,instagram` and fill `post.json`. Follow the title and
      caption formulas in references/hooks.md (top clip-channel patterns), use the audience reactions it includes,
      and keep the credit line and a comment-bait question.
   f. `clipstudio check <job> <clip>` must be ok.
   g. `clipstudio queue <job> <clip> --platforms youtube,tiktok,instagram` (next free slots).
4. If `[post] auto_post = true` in ~/.clipstudio/config.toml: `clipstudio publish` (posts what is due through the
   signed-in browser profile; later slots are posted by the next run or a cron `clipstudio publish`).
   Otherwise leave items as needs_approval.
5. Finish with a short summary: clips made (paths), hooks, what was queued/posted, anything that failed.
