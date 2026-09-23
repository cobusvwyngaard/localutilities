"""How the engine is running: from a source checkout (development) or as the portable app.

The portable app (DESIGN.md §6.3) is a PyInstaller folder:

    Werkbank/
      Werkbank.exe      the engine
      _internal/        Python, the engine's packages, the built UI and tools.json
      bin/              ffmpeg, ffprobe, deno and the standalone yt-dlp

Nothing is installed: no admin rights, no PATH changes, no Python or Node.js on the machine.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Folder that holds `apps/web/dist` and `packages/shared/dist` (the repository in development)."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def programs_dir(env: Mapping[str, str] = os.environ) -> Path | None:
    """Folder with the bundled programs, searched before PATH. `WERKBANK_BIN` overrides it (tests)."""
    if env.get("WERKBANK_BIN"):
        return Path(env["WERKBANK_BIN"])
    if FROZEN:
        return Path(sys.executable).parent / "bin"
    return None


def ytdlp_executable(env: Mapping[str, str] = os.environ) -> Path | None:
    """The standalone yt-dlp in the programs folder, if there is one.

    The portable app uses it instead of the Python package: it updates itself (`yt-dlp -U`) without
    uv or pip, and it includes yt-dlp-ejs."""
    folder = programs_dir(env)
    if folder is None:
        return None
    for name in ("yt-dlp.exe", "yt-dlp"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None
