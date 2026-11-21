# Editing guide: the viral clip-channel standard

The defaults already render this style. This guide is for judging the result and adjusting it.

## Pacing
- **The first second decides the scroll.** Start on action, or on the line that creates the question. Never open on
  a menu, a loading screen or "okay so…". `--trim` and re-cut until it does.
- **One moment per clip:** setup → payoff → reaction, 15–45 s. End right after the reaction peaks (loopable).
- **Dead air is cut automatically.** Gaps with no speech and low sound are removed (`--no-tighten` to keep them).

## Layouts
| layout | when | what it does |
|---|---|---|
| `facecam` | streamer webcam overlay, reaction matters | cam 1080×740 on top (snapped to the overlay border, cropped around the face so the head is never cut), gameplay 1080×1180 below with letterbox bars removed, headline on the seam over a soft dark band |
| `blur` | no webcam, compilations, cinematic scenes | full 16:9 frame in the middle over a heavily blurred, darkened copy. Headline above the frame, captions below, so nothing covers the action |
| `track` | talking / IRL / podcast footage | auto-reframe: the 9:16 frame follows whoever speaks (mouth movement), holds, and hard-cuts between people |
| `fill` | centered action, no cam | full-height crop, `--focus 0..1` |

## Captions: 8 animated styles (`--style`, preview with `clipstudio styles <job> <clip>`)
| style | look | best for |
|---|---|---|
| `auto` (default) | picks one of the styles below per clip, from talking pace, energy, layout and amount of speech | everything |
| `stream` | ONE word at a time, Anton, white/yellow alternating, heavy outline, pop-in | stream clips (top streamer-clip channels) |
| `hormozi` | 2 words, Anton caps, spoken word green, key words gold | commentary, talking |
| `beast` | 1–2 words, chunky cartoon font, yellow active word, slight tilt, bounce | high-energy moments |
| `box` | 2–3 words, colored plate behind the spoken word | punchy explainers |
| `karaoke` | 3–4 words visible, highlight follows the voice, upcoming words dimmed | fast talkers, songs |
| `spotlight` | one big glowing word | hype edits, trailers |
| `neon` | Bebas with neon glow | gaming / night scenes |
| `minimal` | sentence case, small, soft shadow | calm, cinematic |

Every style animates frame by frame: words pop in small, overshoot, then settle. **Auto-size:** short words grow and
long words shrink to fit the safe area. **Auto-emphasis:** numbers, hype words, swears, SHOUTED words and `!` get
bigger and the emphasis color. Fillers ("um", "uh") are dropped. Swears are censored (`--no-censor`). Non-speech
moments can get action captions (`*LAUGHS*`, `*SCREAMS*`): add them to `words.json`, and whisper's own `[laughs]`
tokens are converted automatically. Keyword emoji (💀 crash, 😂 laugh, 💰 money…) pop above the captions (`--emoji auto`).
Placement: middle of the gameplay (facecam), below the frame (blur), lower third (track), and never in the bottom
400 px or under the right-side buttons. Captions are off for already-captioned sources (`--style none`).

## Headline and title
- `--hook`: ≤ 8 words, outlined white with no cheap box. Wrap a word in `*stars*` to color it; emoji are allowed
  ("…*THIS* happens 😭"). Shows for `--hook-secs` (3.5 by default), then the `--title` (2–4 words naming the moment)
  takes over. `--headline-style box` gives the classic white box if you really want it.
- Hook formulas: *"He did NOT expect this…"*, *"Nobody noticed ___"*, *"Wait for it…"*, *"This is why ___"*,
  *"Chat lost it when ___"*, *"Worst ___ in GTA 6"*. Curiosity, stakes, reaction. No lies, and no spoiling the payoff.

## Zoom cuts
Framing alternates between 100 % and 106 % at phrase breaks (`--no-zoomcuts` to disable). It's the jump-cut punch-in
editors use to keep a static shot feeling alive.

## Impact moments
`--punch 12.4` (seconds in raw-clip time) at the payoff frame gives you all of these:
- a 13 % zoom punch that eases out;
- camera shake;
- a 2-frame flash;
- a synthesized boom and pop;
- an emoji pop (`--emoji 💀`, or `auto` picks from nearby words).

Automatic detection only fires on sharp sound jumps (13 dB above the clip's typical level and 7 dB above the previous
second). Give the real second whenever you know it. Use one or two per clip; more becomes noise.

## Sound design (auto, `--sfx auto|minimal|off`)
All effects are synthesized in the tool, so they're licence-free. Drop your own `assets/sfx/<name>.wav` to override
any of them. The kit: whoosh, whoosh_heavy, whip, riser, boom, hit, pop, click, ding, bass_drop, scratch, shutter.

Placement, following what viral editors do:

| moment | sound |
|---|---|
| hook appears | heavy whoosh + hit (pattern interrupt) |
| impact / payoff (`--punch`) | riser building into a deep boom, plus a whip on the shake |
| zoom cut | light whip, with a 2-frame whip-blur on screen |
| keyword emoji pop | pop |
| `*ACTION*` caption | hit |
| hook gives way to title | click |
| end card (`--cta`) | ding |

Effects sit about 6 dB under the voice, and everything is normalized to -14 LUFS.

**Music bed:** `--music phonk|trap|chill` are original synthesized beat loops (drums + 808), so nothing gets claimed.
`--music auto` uses tracks you put in `assets/music/`, or falls back to a generated beat. Music runs low (about
-22 dB) and ducks under speech. Top stream-clip channels keep a steady beat under the whole clip.

**Visual punctuation:** impacts get a warm color flash, a zoom punch and a shake. Zoom cuts get a whip-blur.

## Look
A light contrast and saturation boost plus sharpening (`--no-grade` turns it off). An optional thin progress bar
(`--progress`) is off by default because it can hurt looping.

## Self-check after every render
Pull frames at 0.5 s, 25 %, 50 %, at the punch, and near the end. Check:
- the face is fully visible;
- the captions are readable and not shouting;
- the headline doesn't sit over a busy area;
- the impact lands on the action;
- no black bars or leftover gameplay strips in the cam panel.

If anything is off, fix it with flags (`--facecam`, `--focus`, `--trim`, `--cap-size`, `--layout`) and render again.
