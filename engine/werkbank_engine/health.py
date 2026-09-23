"""GET /api/health: engine version, dependencies, hardware encoders and free disk space."""

from __future__ import annotations

import asyncio
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
    def __init__(self, settings: Settings, tool_count: int, prober: DependencyProber | None = None) -> None:
        self._settings = settings
        self._tool_count = tool_count
        self._prober = prober or DependencyProber()
        self._lock = asyncio.Lock()
        self._deps: list[DependencyResult] | None = None
        self._encoders = EncoderResult()
        self._checked_at = datetime.now(UTC)
        self._probed_monotonic = 0.0

    async def refresh(self) -> None:
        async with self._lock:
            await self._refresh_locked()

    async def _refresh_locked(self) -> None:
        self._deps, self._encoders = await self._prober.probe_all()
        self._checked_at = datetime.now(UTC)
        self._probed_monotonic = time.monotonic()

    async def report(self, refresh: bool = False) -> HealthReport:
        async with self._lock:
            stale = time.monotonic() - self._probed_monotonic > CACHE_SECONDS
            if refresh or self._deps is None or stale:
                await self._refresh_locked()
            deps = list(self._deps or [])
            encoders = self._encoders
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
            hardware_encoders=HardwareEncoders(listed=encoders.listed, usable=encoders.usable),
            disk=disk,
            folders=Folders(inbox=str(self._settings.inbox), outbox=str(self._settings.outbox)),
            tools=self._tool_count,
            checked_at=checked_at,
        )
