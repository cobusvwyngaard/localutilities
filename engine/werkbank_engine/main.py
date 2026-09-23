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
from fastapi import APIRouter, Depends, FastAPI, Query, Request

from werkbank_engine import __version__
from werkbank_engine.config import ConfigError, Settings, load_settings
from werkbank_engine.health import HealthReport, HealthService
from werkbank_engine.registry import RegistryError, load_registry
from werkbank_engine.security import LoopbackGuardMiddleware, require_api_access
from werkbank_engine.webui import mount_web_ui

BIND_HOST = "127.0.0.1"  # never 0.0.0.0 (DESIGN.md §6)

# Every route on this router gets the shared security dependency.
api = APIRouter(prefix="/api", dependencies=[Depends(require_api_access)])


@api.get("/health", response_model=HealthReport, response_model_by_alias=True)
async def health(request: Request, refresh: bool = Query(default=False)) -> HealthReport:
    service: HealthService = request.app.state.health
    return await service.report(refresh=refresh)


def create_app(settings: Settings | None = None, health_service: HealthService | None = None) -> FastAPI:
    settings = settings or load_settings()
    registry = load_registry(settings.registry_path)
    health_service = health_service or HealthService(settings, tool_count=len(registry.tools))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        for folder in (settings.inbox, settings.outbox):
            folder.mkdir(parents=True, exist_ok=True)
        warmup = asyncio.create_task(health_service.refresh())  # probe dependencies in the background
        try:
            yield
        finally:
            warmup.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await warmup

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="werkbank-engine", description="Werkbank local engine")
    parser.add_argument("--open", action="store_true", help="open the UI in the browser once ready")
    parser.add_argument("--port", type=int, help="override the port from the config file")
    args = parser.parse_args(argv)

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
    )
    return 0
