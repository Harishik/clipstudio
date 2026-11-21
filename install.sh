#!/usr/bin/env bash
# ClipStudio installer: Python deps + `clipstudio` command + skill links for your coding agents.
#
#   curl -fsSL https://raw.githubusercontent.com/Harishik/clipstudio/main/install.sh | bash -s -- --all
#   bash install.sh --claude --codex          # pick agents
#   bash install.sh --deps-only               # just the tool
#
# Agents: --claude --codex --gemini --antigravity --opencode --all   |  --dir <skills folder> for anything else
set -euo pipefail

REPO="https://github.com/Harishik/clipstudio.git"
HOME_DIR="${CLIPSTUDIO_HOME:-$HOME/.clipstudio}"
APP="$HOME_DIR/app"
VENV="$HOME_DIR/venv"
BIN="$HOME/.local/bin"

targets=()
deps_only=0
for a in "$@"; do
  case "$a" in
    --claude|--codex|--gemini|--antigravity|--opencode) targets+=("${a#--}") ;;
    --all) targets=(claude codex gemini antigravity opencode) ;;
    --deps-only) deps_only=1 ;;
    --dir=*) targets+=("dir:${a#--dir=}") ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option $a"; exit 1 ;;
  esac
done

say() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }

# 1) source: this checkout, or clone/update into ~/.clipstudio/app
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SRC" ] && [ -f "$SRC/SKILL.md" ] && [ -f "$SRC/scripts/clipstudio.py" ]; then
  APP="$SRC"
else
  command -v git >/dev/null || { echo "git is required"; exit 1; }
  if [ -d "$APP/.git" ]; then say "updating $APP"; git -C "$APP" pull --ff-only -q
  else say "cloning into $APP"; mkdir -p "$HOME_DIR"; git clone -q --depth 1 "$REPO" "$APP"; fi
fi

# 2) system tools
if ! command -v ffmpeg >/dev/null; then
  say "ffmpeg not found"
  if command -v brew >/dev/null; then brew install ffmpeg
  elif command -v apt-get >/dev/null; then sudo apt-get update -y && sudo apt-get install -y ffmpeg
  elif command -v winget >/dev/null; then winget install -e --id Gyan.FFmpeg
  else echo "please install ffmpeg, then re-run"; exit 1; fi
fi
PY="$(command -v python3 || command -v python)"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'

# 3) python env + command
if [ ! -x "$VENV/bin/python" ]; then say "creating $VENV"; "$PY" -m venv "$VENV"; fi
say "installing python packages (yt-dlp, streamlink, faster-whisper, …)"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r "$APP/requirements.txt"
# posting uses your installed Google Chrome; without Chrome, fetch Playwright's free Chromium
if ! [ -d "/Applications/Google Chrome.app" ] && ! command -v google-chrome >/dev/null && ! command -v google-chrome-stable >/dev/null; then
  "$VENV/bin/python" -m playwright install chromium || say "could not install Chromium (posting only)"
fi
mkdir -p "$BIN"
cat > "$BIN/clipstudio" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" "$APP/scripts/clipstudio.py" "\$@"
EOF
chmod +x "$BIN/clipstudio"
case ":$PATH:" in *":$BIN:"*) ;; *) say "add $BIN to your PATH (e.g. echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc)";; esac
[ -f "$HOME_DIR/config.toml" ] || { cp "$APP/config.example.toml" "$HOME_DIR/config.toml"; say "config: $HOME_DIR/config.toml"; }

[ "$deps_only" = 1 ] && { say "done (deps only)"; exit 0; }

# 4) agent skill links (symlinks, so `git pull` updates every agent at once)
link() { mkdir -p "$1"; ln -sfn "$APP" "$1/clipstudio"; say "linked → $1/clipstudio"; }
for t in "${targets[@]:-}"; do
  case "$t" in
    claude)      link "$HOME/.claude/skills" ;;
    codex)       link "${CODEX_HOME:-$HOME/.codex}/skills" ;;
    antigravity) link "$HOME/.gemini/antigravity/skills" ;;
    opencode)    link "$HOME/.config/opencode/skills" ;;
    gemini)
      if command -v gemini >/dev/null; then gemini extensions link "$APP" || link "$HOME/.gemini/extensions"
      else link "$HOME/.gemini/extensions"; fi ;;
    dir:*)       link "${t#dir:}" ;;
    "") ;;
  esac
done
say "done. Try: clipstudio doctor   |   in your agent: \"use clipstudio to clip <stream url>\""
