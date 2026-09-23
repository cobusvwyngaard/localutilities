"""The job queue (DESIGN.md §3.2): queued → running → done | failed | cancelled.

Each job runs in its own scratch folder; outputs are moved to the Outbox only when the job
succeeds, so a cancelled or failed job never leaves partial files behind.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import shutil
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from werkbank_engine.config import Settings
from werkbank_engine.files import FileError, FileStore, resolve_inbox, unique_path
from werkbank_engine.health import HealthService
from werkbank_engine.procs import ProcessError, stream_exec
from werkbank_engine.registry import RegistryFile, ToolDef, validate_params

log = logging.getLogger("werkbank.jobs")

Status = Literal["queued", "running", "done", "failed", "cancelled"]
TERMINAL: frozenset[str] = frozenset({"done", "failed", "cancelled"})
MAX_KEPT_JOBS = 100
MAX_URL_LENGTH = 2048


class ToolError(Exception):
    """A job failed for a reason the user can act on; the message is shown as is."""


class JobRequestError(ValueError):
    """The job request is invalid (HTTP 400); the message is safe to show."""


class InputRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fileId: str | None = Field(default=None, max_length=64)
    inbox: str | None = Field(default=None, max_length=1000)
    url: str | None = Field(default=None, max_length=MAX_URL_LENGTH)

    @model_validator(mode="after")
    def exactly_one(self) -> InputRef:
        if sum(v is not None for v in (self.fileId, self.inbox, self.url)) != 1:
            raise ValueError("each input needs exactly one of fileId, inbox or url")
        return self


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[InputRef] = Field(max_length=1000)


@dataclass(frozen=True)
class JobInput:
    kind: Literal["file", "url"]
    name: str  # display name: original file name or the URL
    path: Path | None = None
    url: str | None = None


@dataclass
class JobOutput:
    name: str
    path: Path
    size: int


@dataclass
class Job:
    id: str
    tool: ToolDef
    title: str
    inputs: list[JobInput]
    params: dict[str, Any]
    status: Status = "queued"
    progress: float | None = None
    message: str | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    outputs: list[JobOutput] = field(default_factory=list)
    log: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    version: int = 0
    task: asyncio.Task[None] | None = None
    _changed: asyncio.Event = field(default_factory=asyncio.Event)

    def touch(self) -> None:
        self.version += 1
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def snapshot(self) -> dict[str, Any]:
        """What the UI sees. Never includes parameters (a PDF password, for example)."""
        return {
            "id": self.id,
            "tool": self.tool.id,
            "toolTitle": self.tool.title,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "notes": list(self.notes),
            "error": self.error,
            "outputs": [{"index": i, "name": o.name, "size": o.size} for i, o in enumerate(self.outputs)],
            "log": list(self.log)[-30:],
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


class ToolContext:
    """What a tool implementation gets: validated inputs and params, a scratch folder, and
    ways to report progress, run programs and hand over outputs."""

    def __init__(self, job: Job, work: Path, programs: Mapping[str, str], health: HealthService) -> None:
        self.job = job
        self.work = work
        self._programs = programs
        self._health = health
        self._pending_outputs: list[tuple[Path, str]] = []
        self._last_touch = 0.0

    @property
    def inputs(self) -> list[JobInput]:
        return self.job.inputs

    @property
    def params(self) -> dict[str, Any]:
        return self.job.params

    def program(self, dependency_id: str) -> str:
        path = self._programs.get(dependency_id)
        if not path:
            raise ToolError(f"{dependency_id} is not installed. See the Status page for how to install it.")
        return path

    async def usable_hardware_encoders(self) -> list[str]:
        await self._health.wait_for_encoders()
        report = await self._health.report()
        return report.hardware_encoders.usable

    def progress(self, fraction: float | None, message: str | None = None) -> None:
        if fraction is not None:
            fraction = min(max(fraction, 0.0), 1.0)
        changed = fraction != self.job.progress or (message is not None and message != self.job.message)
        self.job.progress = fraction
        if message is not None:
            self.job.message = message
        now = time.monotonic()
        if changed and (message is not None or now - self._last_touch > 0.25):
            self._last_touch = now
            self.job.touch()

    def note(self, text: str) -> None:
        """A line for the result, e.g. "No quality loss: streams were copied"."""
        self.job.notes.append(text)
        self.job.touch()

    def log(self, line: str) -> None:
        self.job.log.append(line[:500])

    def add_output(self, path: Path, name: str) -> None:
        """`path` (inside the scratch folder) becomes Outbox/`name` if the job succeeds."""
        self._pending_outputs.append((path, name))

    async def run(
        self,
        args: Sequence[str],
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
        env: Mapping[str, str] | None = None,
        what: str | None = None,
    ) -> None:
        """Run a program (argument list); raises ToolError with its last error lines on failure."""
        errors: deque[str] = deque(maxlen=8)

        def stderr(line: str) -> None:
            errors.append(line)
            self.log(line)
            if on_stderr:
                on_stderr(line)

        def stdout(line: str) -> None:
            if on_stdout:
                on_stdout(line)
            else:
                self.log(line)

        try:
            code = await stream_exec(args, stdout, stderr, cwd=self.work, env=env)
        except ProcessError as exc:
            raise ToolError(str(exc)) from exc
        if code != 0:
            detail = "\n".join(errors) or f"exit code {code}"
            raise ToolError(f"{what or Path(args[0]).name} failed: {detail}")


def _validate_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or any(c.isspace() or ord(c) < 32 for c in url)
        or len(url) > MAX_URL_LENGTH
    ):
        raise JobRequestError("Enter a full web address starting with http:// or https://.")
    return url


class JobManager:
    def __init__(
        self,
        settings: Settings,
        registry: RegistryFile,
        health: HealthService,
        files: FileStore,
        implementations: Mapping[str, ModuleType],
        heavy_slots: int = 1,
        light_slots: int = 3,
    ) -> None:
        self._settings = settings
        self._tools = {t.id: t for t in registry.tools}
        self._health = health
        self._files = files
        self._impl = implementations
        self._heavy = asyncio.Semaphore(heavy_slots)
        self._light = asyncio.Semaphore(light_slots)
        self._outbox_lock = asyncio.Lock()
        self._jobs: OrderedDict[str, Job] = OrderedDict()

    # --- submitting ---------------------------------------------------------------------------

    def _resolve_inputs(self, tool: ToolDef, refs: list[InputRef]) -> list[JobInput]:
        spec = tool.inputs
        if not spec.min <= len(refs) <= spec.max:
            raise JobRequestError(
                f"{tool.title} takes {spec.min}"
                + (f" to {spec.max}" if spec.max != spec.min else "")
                + " input(s)."
            )
        resolved: list[JobInput] = []
        for ref in refs:
            if ref.url is not None:
                if "url" not in spec.kinds:
                    raise JobRequestError(f"{tool.title} does not take web addresses.")
                url = _validate_url(ref.url)
                resolved.append(JobInput(kind="url", name=url, url=url))
                continue
            if "file" not in spec.kinds:
                raise JobRequestError(f"{tool.title} takes a web address, not a file.")
            try:
                if ref.fileId is not None:
                    stored = self._files.get(ref.fileId)
                    path, name = stored.path, stored.name
                else:
                    path = resolve_inbox(self._settings.inbox, ref.inbox or "")
                    name = path.name
            except FileError as exc:
                raise JobRequestError(str(exc)) from exc
            if spec.accept and path.suffix.lower() not in spec.accept:
                raise JobRequestError(f"'{name}' is not a supported file type ({', '.join(spec.accept)}).")
            resolved.append(JobInput(kind="file", name=name, path=path))
        return resolved

    def submit(self, request: JobRequest) -> Job:
        tool = self._tools.get(request.tool)
        if tool is None or "engine" not in tool.runsIn or request.tool not in self._impl:
            raise JobRequestError(f"Unknown engine tool '{request.tool}'.")
        params = validate_params(tool, request.params)  # ParamError is a ValueError: HTTP 400
        inputs = self._resolve_inputs(tool, request.inputs)
        title = inputs[0].name if len(inputs) == 1 else f"{inputs[0].name} and {len(inputs) - 1} more"
        job = Job(id=secrets.token_urlsafe(9), tool=tool, title=title, inputs=inputs, params=params)
        self._jobs[job.id] = job
        self._forget_old_jobs()
        job.task = asyncio.create_task(self._run(job))
        return job

    def _forget_old_jobs(self) -> None:
        finished = [j for j in self._jobs.values() if j.status in TERMINAL]
        for job in finished[: max(0, len(self._jobs) - MAX_KEPT_JOBS)]:
            self._jobs.pop(job.id, None)

    # --- running ------------------------------------------------------------------------------

    async def _programs_for(self, tool: ToolDef) -> dict[str, str]:
        report = await self._health.report()
        by_id = {d.id: d for d in report.dependencies}
        missing = [by_id[r] for r in tool.requires if r in by_id and not by_id[r].available]
        if missing:
            fixes = "; ".join(f"{d.name}: {d.fix}" if d.fix else d.name for d in missing)
            raise ToolError(f"Missing: {fixes}")
        return {d.id: d.path for d in report.dependencies if d.available and d.path}

    async def _run(self, job: Job) -> None:
        module = self._impl[job.tool.id]
        semaphore = self._heavy if getattr(module, "HEAVY", False) else self._light
        work = self._settings.work_dir / "jobs" / job.id
        try:
            async with semaphore:
                job.status = "running"
                job.started_at = time.time()
                job.touch()
                work.mkdir(parents=True, exist_ok=True)
                context = ToolContext(job, work, await self._programs_for(job.tool), self._health)
                await module.run(context)
                await self._deliver(job, context)
                job.status = "done"
                job.progress = 1.0
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.message = "Cancelled"
        except ToolError as exc:
            job.status = "failed"
            job.error = str(exc)
        except Exception as exc:
            log.exception("job %s (%s) crashed", job.id, job.tool.id)
            job.status = "failed"
            job.error = f"Unexpected error: {exc}"
        finally:
            job.finished_at = time.time()
            await asyncio.to_thread(shutil.rmtree, work, True)
            job.touch()

    async def _deliver(self, job: Job, context: ToolContext) -> None:
        outbox = self._settings.outbox
        outbox.mkdir(parents=True, exist_ok=True)
        for path, name in context._pending_outputs:
            async with self._outbox_lock:  # choose the name and move atomically w.r.t. other jobs
                target = unique_path(outbox, name)
                await asyncio.to_thread(shutil.move, os.fspath(path), os.fspath(target))
            job.outputs.append(JobOutput(name=target.name, path=target, size=target.stat().st_size))

    # --- querying -----------------------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(reversed(self._jobs.values()))

    async def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status not in TERMINAL and job.task is not None:
            job.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(job.task)
        return job

    async def events(self, job_id: str, min_interval: float = 0.2) -> AsyncIterator[str]:
        """Server-sent events: the job's snapshot on every change, until it finishes."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        while True:
            changed = job._changed
            yield f"data: {json.dumps(job.snapshot())}\n\n"
            if job.status in TERMINAL:
                return
            try:
                await asyncio.wait_for(changed.wait(), 15)
            except TimeoutError:
                yield ": keep-alive\n\n"
            await asyncio.sleep(min_interval)

    async def shutdown(self) -> None:
        running = [j.task for j in self._jobs.values() if j.task is not None and not j.task.done()]
        for task in running:
            task.cancel()
        for task in running:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
