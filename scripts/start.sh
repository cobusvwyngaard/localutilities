#!/usr/bin/env bash
# Starts the Werkbank engine and opens http://127.0.0.1:8765 (DESIGN.md section 6.4). Ctrl+C stops it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$HOME/.local/bin:$HOME/.deno/bin:$PATH"
command -v uv >/dev/null 2>&1 || { echo "uv was not found. Run scripts/install.sh first." >&2; exit 1; }
exec uv run --project engine --frozen --no-dev werkbank-engine --open "$@"
