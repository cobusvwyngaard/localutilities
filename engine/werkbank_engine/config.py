"""Engine settings: the API token, port, Inbox/Outbox folders and the allowed hosted origins.

Stored as JSON in the per-user config directory and created on first run (DESIGN.md §6.2).
Environment overrides exist for tests and development only.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_HOSTED_ORIGINS = ("https://localutilities.cobus-w.workers.dev",)
_ORIGIN_RE = re.compile(
    r"^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(:\d{1,5})?$"
)
_MIN_TOKEN_LENGTH = 32

# engine/werkbank_engine/config.py -> repository root (the engine runs from a source checkout).
REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """The config file exists but is unusable; the message says what to fix."""


@dataclass(frozen=True)
class Settings:
    home: Path
    token: str
    port: int
    inbox: Path
    outbox: Path
    hosted_origins: tuple[str, ...]
    web_dist: Path
    registry_path: Path

    @property
    def config_file(self) -> Path:
        return self.home / "config.json"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        local = {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}
        return frozenset(local | set(self.hosted_origins))


def default_home(env: Mapping[str, str] = os.environ) -> Path:
    if env.get("WERKBANK_HOME"):
        return Path(env["WERKBANK_HOME"])
    if sys.platform == "win32":
        return Path(env.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Werkbank"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Werkbank"
    return Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "werkbank"


def _write_private(path: Path, text: str) -> None:
    """Write atomically; on POSIX the file is readable by the owner only (it holds the token)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    tmp.replace(path)


def _validate(data: dict, config_file: Path) -> None:
    def fail(msg: str) -> ConfigError:
        return ConfigError(f"{config_file}: {msg}")

    token = data.get("token")
    if not isinstance(token, str) or len(token) < _MIN_TOKEN_LENGTH or not token.isascii():
        raise fail(f"'token' must be an ASCII string of at least {_MIN_TOKEN_LENGTH} characters")
    port = data.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise fail("'port' must be an integer between 1024 and 65535")
    for key in ("inbox", "outbox"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise fail(f"'{key}' must be a folder path")
    origins = data.get("hostedOrigins")
    if not isinstance(origins, list) or not all(isinstance(o, str) and _ORIGIN_RE.match(o) for o in origins):
        raise fail(
            "'hostedOrigins' must be a list of https:// origins without a path, e.g. https://example.com"
        )


def load_settings(env: Mapping[str, str] = os.environ, port_override: int | None = None) -> Settings:
    home = default_home(env)
    config_file = home / "config.json"
    folders_root = Path(env["WERKBANK_FOLDERS"]) if env.get("WERKBANK_FOLDERS") else Path.home() / "Werkbank"
    defaults = {
        "port": DEFAULT_PORT,
        "inbox": str(folders_root / "Inbox"),
        "outbox": str(folders_root / "Outbox"),
        "hostedOrigins": list(DEFAULT_HOSTED_ORIGINS),
    }

    data: dict = {}
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"{config_file}: cannot read ({exc}). Fix or delete it.") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{config_file}: expected a JSON object. Fix or delete it.")

    changed = False
    if "token" not in data:
        data["token"] = secrets.token_urlsafe(32)  # 32 random bytes
        changed = True
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
            changed = True
    _validate(data, config_file)
    if changed:
        _write_private(config_file, json.dumps(data, indent=2) + "\n")

    port = data["port"]
    if env.get("WERKBANK_PORT"):
        port = int(env["WERKBANK_PORT"])
    if port_override is not None:
        port = port_override

    return Settings(
        home=home,
        token=data["token"],
        port=port,
        inbox=Path(data["inbox"]).expanduser(),
        outbox=Path(data["outbox"]).expanduser(),
        hosted_origins=tuple(data["hostedOrigins"]),
        web_dist=Path(env.get("WERKBANK_WEB_DIST") or REPO_ROOT / "apps" / "web" / "dist"),
        registry_path=Path(
            env.get("WERKBANK_REGISTRY") or REPO_ROOT / "packages" / "shared" / "dist" / "tools.json"
        ),
    )
