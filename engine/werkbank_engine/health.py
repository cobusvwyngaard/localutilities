"""GET /api/health: engine version, dependencies, hardware encoders and free disk space."""

from __future__ import annotations

import asyncio
import contextlib
import platform
import shutil
import time
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from werkbank_engine import __version__
from werkbank_engine.config import Settings
from werkbank_engine.deps import DependencyProber, DependencyResult, EncoderResult

CACHE_SECONDS = 600


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DependencyStatus(CamelModel):
    id: str
    name: str
    required: bool
    available: bool
    version: str | None
    path: str | None
    needed_for: str
    fix: str | None
    detail: str | None


class HardwareEncoders(CamelModel):
    listed: list[str]
    usable: list[str]
    checking: bool  # test encodes still running in the background


class DiskInfo(CamelModel):
    path: str
    free_bytes: int
    total_bytes: int


class EngineInfo(CamelModel):
    version: str
    python: str
    platform: str


class Folders(CamelModel):
    inbox: str
    outbox: str


class HealthReport(CamelModel):
    status: Literal["ok", "degraded"]
    engine: EngineInfo
    dependencies: list[DependencyStatus]
    hardware_encoders: HardwareEncoders
    disk: DiskInfo | None
    folders: Folders
    tools: int
    checked_at: datetime


def _status(deps: list[DependencyResult]) -> Literal["ok", "degraded"]:
    return "ok" if all(d.available for d in deps if d.required) else "degraded"


class HealthService:
    """Dependency checks are quick and decide the status; hardware-encoder test encodes can take
    tens of seconds (one ffmpeg run per GPU encoder), so they run in the background."""

    def __init__(self, settings: Settings, tool_count: int, prober: DependencyProber | None = None) -> None:
        self._settings = settings
        self._tool_count = tool_count
        self._prober = prober or DependencyProber()
        self._lock = asyncio.Lock()
        self._deps: list[DependencyResult] | None = None
        self._encoders = EncoderResult()
        self._encoder_task: asyncio.Task[None] | None = None
        self._checked_at = datetime.now(UTC)
        self._probed_monotonic = 0.0

    async def refresh(self) -> None:
        async with self._lock:
            await self._refresh_locked()

    async def _refresh_locked(self) -> None:
        self._deps = await self._prober.probe_dependencies()
        self._checked_at = datetime.now(UTC)
        self._probed_monotonic = time.monotonic()
        ffmpeg = next((d for d in self._deps if d.id == "ffmpeg"), None)
        self._restart_encoder_probe(ffmpeg.path if ffmpeg and ffmpeg.available else None)

    def _restart_encoder_probe(self, ffmpeg_path: str | None) -> None:
        if self._encoder_task is not None and not self._encoder_task.done():
            self._encoder_task.cancel()
        self._encoder_task = None
        if ffmpeg_path is None:
            self._encoders = EncoderResult()
            return

        async def probe() -> None:
            self._encoders = await self._prober.probe_encoders(ffmpeg_path)

        self._encoder_task = asyncio.create_task(probe())

    @property
    def encoders_checking(self) -> bool:
        return self._encoder_task is not None and not self._encoder_task.done()

    async def wait_for_encoders(self) -> None:
        if self._encoder_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(self._encoder_task)

    async def close(self) -> None:
        if self._encoder_task is not None and not self._encoder_task.done():
            self._encoder_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._encoder_task

    async def report(self, refresh: bool = False) -> HealthReport:
        async with self._lock:
            stale = time.monotonic() - self._probed_monotonic > CACHE_SECONDS
            if refresh or self._deps is None or stale:
                await self._refresh_locked()
            deps = list(self._deps or [])
            encoders = self._encoders
            checking = self.encoders_checking
            checked_at = self._checked_at

        disk = None
        try:
            usage = shutil.disk_usage(self._settings.outbox)
            disk = DiskInfo(path=str(self._settings.outbox), free_bytes=usage.free, total_bytes=usage.total)
        except OSError:
            pass

        return HealthReport(
            status=_status(deps),
            engine=EngineInfo(
                version=__version__, python=platform.python_version(), platform=platform.platform(terse=True)
            ),
            dependencies=[
                DependencyStatus(
                    id=d.id,
                    name=d.name,
                    required=d.required,
                    available=d.available,
                    version=d.version,
                    path=d.path,
                    needed_for=d.needed_for,
                    fix=d.fix,
                    detail=d.detail,
                )
                for d in deps
            ],
            hardware_encoders=HardwareEncoders(
                listed=[] if checking else encoders.listed,
                usable=[] if checking else encoders.usable,
                checking=checking,
            ),
            disk=disk,
            folders=Folders(inbox=str(self._settings.inbox), outbox=str(self._settings.outbox)),
            tools=self._tool_count,
            checked_at=checked_at,
        )
