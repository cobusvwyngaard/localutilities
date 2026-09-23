#!/usr/bin/env bash
# Installs or updates the Werkbank engine on macOS (Homebrew) or Debian/Ubuntu Linux.
# Installs uv, FFmpeg, Deno and Node.js if missing, sets up the engine's Python environment
# and builds the UI the engine serves. Safe to re-run after `git pull`.
#
#   scripts/install.sh [--no-start]
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
min_node_major=22
start=1
for arg in "$@"; do
  case "$arg" in
    --no-start) start=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
export PATH="$HOME/.local/bin:$HOME/.deno/bin:$PATH"

node_major() { node --version 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/'; }

step "Checking programs (uv, FFmpeg, Deno, Node.js)"
case "$(uname -s)" in
  Darwin)
    have brew || { echo "Homebrew is needed: https://brew.sh" >&2; exit 1; }
    have uv || brew install uv
    have ffmpeg || brew install ffmpeg
    have deno || brew install deno
    have node || brew install node
    ;;
  Linux)
    have apt-get || { echo "Only Debian/Ubuntu (apt) is supported by this script." >&2; exit 1; }
    if ! have ffmpeg; then
      sudo apt-get update
      sudo apt-get install -y ffmpeg
    fi
    # Official installers; both install into the user's home folder.
    have uv || curl -LsSf https://astral.sh/uv/install.sh | sh
    have deno || curl -fsSL https://deno.land/install.sh | sh -s -- -y
    have node || { echo "Install Node.js $min_node_major or newer (https://nodejs.org), then re-run." >&2; exit 1; }
    ;;
  *)
    echo "Unsupported system: $(uname -s). On Windows use scripts\\install.ps1." >&2
    exit 1
    ;;
esac

for cmd in uv ffmpeg deno node npm; do
  have "$cmd" || { echo "'$cmd' is still not found. Open a new terminal and run this script again." >&2; exit 1; }
done
if [ "$(node_major)" -lt "$min_node_major" ]; then
  echo "Node.js $min_node_major or newer is needed (found $(node --version))." >&2
  exit 1
fi
echo "uv:     $(uv --version)"
echo "FFmpeg: $(ffmpeg -hide_banner -version | head -n 1)"
echo "Deno:   $(deno --version | head -n 1)"
echo "Node:   $(node --version)"

cd "$repo_root"
step "Setting up the engine (Python environment)"
uv sync --project engine --frozen --no-dev

step "Updating yt-dlp to its latest release (sites change often)"
uv run --project engine --no-sync werkbank-engine --update-ytdlp

step "Installing UI packages (npm ci)"
npm ci --no-audit --no-fund

step "Building the user interface"
npm run build -w apps/web

step "Done"
echo "Start Werkbank with scripts/start.sh (opens http://127.0.0.1:8765). Stop it with Ctrl+C."
echo "To update later: git pull, then run this script again."
if [ "$start" -eq 1 ]; then
  exec "$repo_root/scripts/start.sh"
fi
