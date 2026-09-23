"""The /api routes. Every route is on `api`, which carries the shared security dependency."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from werkbank_engine.files import FileStore, list_inbox
from werkbank_engine.health import HealthReport, HealthService
from werkbank_engine.jobs import Job, JobManager, JobRequest, JobRequestError
from werkbank_engine.procs import ProcessError, run_exec
from werkbank_engine.registry import ParamError
from werkbank_engine.runtime import ytdlp_executable
from werkbank_engine.security import require_api_access

api = APIRouter(prefix="/api", dependencies=[Depends(require_api_access)])


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _job(request: Request, job_id: str) -> Job:
    job = _jobs(request).get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    return job


@api.get("/health", response_model=HealthReport, response_model_by_alias=True)
async def health(request: Request, refresh: bool = Query(default=False)) -> HealthReport:
    service: HealthService = request.app.state.health
    return await service.report(refresh=refresh)


@api.post("/files", status_code=201)
async def upload(request: Request, name: str = Query(min_length=1, max_length=255)) -> dict[str, Any]:
    """Upload one file as the raw request body (no multipart: large files stream straight to disk)."""
    store: FileStore = request.app.state.files
    stored = await store.save(name, request.stream())
    return {"fileId": stored.id, "name": stored.name, "size": stored.size}


@api.get("/inbox")
async def inbox(request: Request) -> dict[str, Any]:
    folder = request.app.state.settings.inbox
    return {"folder": str(folder), "files": await asyncio.to_thread(list_inbox, folder)}


@api.post("/jobs", status_code=201)
async def create_job(request: Request, body: JobRequest) -> dict[str, Any]:
    try:
        job = _jobs(request).submit(body)
    except (JobRequestError, ParamError) as exc:
        raise HTTPException(400, str(exc)) from None
    return job.snapshot()


@api.get("/jobs")
async def list_jobs(request: Request) -> list[dict[str, Any]]:
    return [job.snapshot() for job in _jobs(request).all()]


@api.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> dict[str, Any]:
    return _job(request, job_id).snapshot()


@api.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str) -> StreamingResponse:
    _job(request, job_id)
    return StreamingResponse(
        _jobs(request).events(job_id),
        media_type="text/event-stream",
        headers={"cache-control": "no-store"},
    )


@api.delete("/jobs/{job_id}")
async def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    _job(request, job_id)
    job = await _jobs(request).cancel(job_id)
    if job is None:  # pragma: no cover - checked above
        raise HTTPException(404, "No such job.")
    return job.snapshot()


def _output_path(request: Request, job_id: str, index: int) -> tuple[Path, str]:
    job = _job(request, job_id)
    if not 0 <= index < len(job.outputs):
        raise HTTPException(404, "No such output.")
    output = job.outputs[index]
    if not output.path.is_file():
        raise HTTPException(410, "The file is no longer in the Outbox.")
    return output.path, output.name


@api.get("/jobs/{job_id}/outputs/{index}")
async def download_output(request: Request, job_id: str, index: int) -> FileResponse:
    path, name = _output_path(request, job_id, index)
    return FileResponse(path, filename=name)


@api.post("/jobs/{job_id}/outputs/{index}/reveal", status_code=204)
async def reveal_output(request: Request, job_id: str, index: int) -> Response:
    """Show the output in Explorer (Finder, file manager). Mode A only makes sense locally."""
    path, _ = _output_path(request, job_id, index)
    if sys.platform == "win32":
        args = ["explorer.exe", "/select,", str(path)]
    elif sys.platform == "darwin":
        args = ["open", "-R", str(path)]
    else:
        args = ["xdg-open", str(path.parent)]
    try:
        await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise HTTPException(500, f"Could not open the folder: {exc}") from None
    return Response(status_code=204)


def find_uv() -> str | None:
    """`uv run` sets UV to its own path; fall back to PATH and the usual install folders."""
    candidates = [os.environ.get("UV"), shutil.which("uv")]
    home = Path.home()
    for folder in (
        home / ".local" / "bin",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links",
    ):
        candidates.append(shutil.which("uv", path=str(folder)))
    return next((c for c in candidates if c), None)


async def update_ytdlp() -> tuple[bool, str]:
    """Update yt-dlp to its latest release (DESIGN.md §5.1).

    Portable app: the standalone executable updates itself (`yt-dlp -U` downloads the release and
    checks it against the published SHA-256 sums); its bin folder must be writable.
    Development: upgrade the package (with yt-dlp-ejs) in the engine's environment with uv."""
    standalone = ytdlp_executable()
    if standalone is not None:
        args = [str(standalone), "--update"]
    else:
        uv = find_uv()
        if uv is None:
            return False, "uv was not found. In the repository run: uv sync --project engine"
        args = [uv, "pip", "install", "--python", sys.executable, "--upgrade", "yt-dlp[default]"]
    try:
        result = await run_exec(args, limit_seconds=300)
    except ProcessError as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).strip().splitlines()
    return result.returncode == 0, "\n".join(output[-10:])


@api.post("/admin/update-ytdlp")
async def admin_update_ytdlp(request: Request) -> dict[str, Any]:
    ok, output = await update_ytdlp()
    service: HealthService = request.app.state.health
    report = await service.report(refresh=True)
    version = next((d.version for d in report.dependencies if d.id == "yt-dlp"), None)
    if not ok:
        raise HTTPException(500, f"Updating yt-dlp failed:\n{output}")
    return {"version": version, "output": output}
