"""FastAPI app factory and the `werkbank-engine` command.

Development: `uv run uvicorn werkbank_engine.main:app --host 127.0.0.1 --port 8765 --reload`
(`app` is created lazily on first access, so importing this module has no side effects).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI

from werkbank_engine import __version__
from werkbank_engine.config import ConfigError, Settings, load_settings
from werkbank_engine.files import FileStore, sweep
from werkbank_engine.health import HealthService
from werkbank_engine.jobs import JobManager
from werkbank_engine.registry import RegistryError, load_registry
from werkbank_engine.routes import api, update_ytdlp
from werkbank_engine.runtime import FROZEN
from werkbank_engine.security import LoopbackGuardMiddleware
from werkbank_engine.tools import IMPLEMENTATIONS
from werkbank_engine.webui import mount_web_ui

BIND_HOST = "127.0.0.1"  # never 0.0.0.0 (DESIGN.md §6)

__all__ = ["api", "create_app", "main"]


def create_app(settings: Settings | None = None, health_service: HealthService | None = None) -> FastAPI:
    settings = settings or load_settings()
    registry = load_registry(settings.registry_path)
    missing = [t.id for t in registry.tools if "engine" in t.runsIn and t.id not in IMPLEMENTATIONS]
    if missing:
        raise RegistryError(f"registry tools without an engine implementation: {', '.join(missing)}")
    health_service = health_service or HealthService(settings, tool_count=len(registry.tools))
    files = FileStore(settings.work_dir / "uploads")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        for folder in (settings.inbox, settings.outbox, files.root, settings.work_dir / "jobs"):
            folder.mkdir(parents=True, exist_ok=True)
        for folder in (files.root, settings.work_dir / "jobs"):  # DESIGN.md §3.3: 24-hour sweep
            await asyncio.to_thread(sweep, folder)
        app.state.jobs = JobManager(settings, registry, health_service, files, IMPLEMENTATIONS)
        warmup = asyncio.create_task(health_service.refresh())  # probe dependencies in the background
        try:
            yield
        finally:
            await app.state.jobs.shutdown()
            warmup.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await warmup
            await health_service.close()

    app = FastAPI(
        title="Werkbank engine",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.health = health_service
    app.state.files = files
    app.include_router(api)
    mount_web_ui(app, settings)
    app.add_middleware(LoopbackGuardMiddleware, settings=settings)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """`werkbank_engine.main:app` for uvicorn, created on first access."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((BIND_HOST, port)) == 0


def _engine_answers(settings: Settings) -> bool:
    """True if the program on our port is this engine (it accepts our token)."""
    req = urllib.request.Request(
        f"http://{BIND_HOST}:{settings.port}/api/health",
        headers={"Authorization": f"Bearer {settings.token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - fixed http://127.0.0.1 URL
            return resp.status == 200 and "engine" in json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _open_when_ready(port: int, url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_in_use(port):
            webbrowser.open(url)
            return
        time.sleep(0.2)


def _disable_quick_edit() -> None:
    """Windows consoles pause a program's output while text is selected ("QuickEdit"); a stray click
    in the Werkbank window would then freeze the engine until Esc is pressed. Turn that off."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    mode = ctypes.c_uint32()
    if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        enable_extended_flags, enable_quick_edit_mode = 0x0080, 0x0040
        kernel32.SetConsoleMode(handle, (mode.value | enable_extended_flags) & ~enable_quick_edit_mode)


def _pause_before_exit() -> None:
    """The portable app runs in its own console window; keep an error readable before it closes."""
    if FROZEN and sys.stdin and sys.stdin.isatty():
        with contextlib.suppress(EOFError, OSError):
            input("Press Enter to close this window.")


def main(argv: list[str] | None = None) -> int:
    code = _main(argv)
    if code not in (0, None):
        _pause_before_exit()
    return code


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="werkbank-engine", description="Werkbank local engine")
    # The portable app is started by double-clicking, so it opens the browser unless told not to.
    parser.add_argument(
        "--open",
        action=argparse.BooleanOptionalAction,
        default=FROZEN,
        help="open the UI in the browser once ready",
    )
    parser.add_argument("--port", type=int, help="override the port from the config file")
    parser.add_argument(
        "--update-ytdlp", action="store_true", help="update yt-dlp to its latest release and exit"
    )
    args = parser.parse_args(argv)

    if args.update_ytdlp:
        ok, output = asyncio.run(update_ytdlp())
        print(output)
        return 0 if ok else 1

    try:
        settings = load_settings(port_override=args.port)
        app = create_app(settings)
    except (ConfigError, RegistryError) as exc:
        print(f"Werkbank engine cannot start: {exc}", file=sys.stderr)
        return 2

    url = f"http://{BIND_HOST}:{settings.port}/"
    if _port_in_use(settings.port):
        if _engine_answers(settings):
            print(f"Werkbank is already running at {url}")
            if args.open:
                webbrowser.open(url)
            return 0
        print(
            f"Port {settings.port} is in use by another program. Close it or set another port "
            f"in {settings.config_file}.",
            file=sys.stderr,
        )
        return 1

    if FROZEN:
        _disable_quick_edit()
    print(f"Werkbank engine {__version__} starting at {url} (close this window to stop it)")
    if args.open:
        threading.Thread(target=_open_when_ready, args=(settings.port, url), daemon=True).start()
    uvicorn.run(
        app,
        host=BIND_HOST,
        port=settings.port,
        proxy_headers=False,
        server_header=False,
        log_level="info",
        access_log=not FROZEN,  # the UI polls /api/health; keep the portable app's window readable
    )
    return 0
