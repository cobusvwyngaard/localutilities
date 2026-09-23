"""Running external programs. Argument lists only — never a shell, never a command string."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


class ProcessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


def _close_transport(proc: asyncio.subprocess.Process) -> None:
    """Close the process's transport now (killing the process if it is somehow still running).

    asyncio closes it through several event-loop callbacks after the process exits; if the loop
    stops first, or the cleanup is cancelled again during shutdown, it would be left open.
    There is no public API for this.
    """
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        transport.close()


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(Exception):  # drain the pipes
        await asyncio.wait_for(proc.communicate(), 5)


async def run_exec(args: Sequence[str], limit_seconds: float = 20.0) -> ExecResult:
    """Run `args[0]` with the remaining arguments and capture its output.

    Raises ProcessError if the program cannot be started or exceeds `limit_seconds`
    (the process is killed first). `limit_seconds` bounds the whole run.
    """
    if not args or not all(isinstance(a, str) for a in args):
        raise ProcessError("args must be a non-empty list of strings")
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except NotImplementedError as exc:  # pragma: no cover - Windows SelectorEventLoop only
        raise ProcessError(
            "This event loop cannot run subprocesses. On Windows, start the engine without --reload."
        ) from exc
    except OSError as exc:
        raise ProcessError(f"cannot start {args[0]}: {exc}") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(), limit_seconds)
    except TimeoutError as exc:
        await _kill(proc)
        raise ProcessError(f"{args[0]} did not finish within {limit_seconds:g} s") from exc
    except asyncio.CancelledError:
        await _kill(proc)  # e.g. engine shutdown: never leave the child running
        raise
    finally:
        _close_transport(proc)
    return ExecResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )


LineHandler = Callable[[str], None]


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the process and everything it started (yt-dlp runs ffmpeg, for example)."""
    if proc.returncode is not None:
        return
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(proc.pid),
                "/T",
                "/F",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), 10)
        except (OSError, TimeoutError):
            pass
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)  # the child leads its own session (start_new_session)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


async def _pump(stream: asyncio.StreamReader, handler: LineHandler) -> None:
    # ffmpeg and yt-dlp may end lines with \r; split on both and never buffer unbounded lines.
    pending = b""
    while chunk := await stream.read(65536):
        pending += chunk
        parts = pending.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
        pending = parts.pop()
        if len(pending) > 65536:
            parts.append(pending)
            pending = b""
        for part in parts:
            if part:
                handler(part.decode("utf-8", "replace"))
    if pending:
        handler(pending.decode("utf-8", "replace"))


async def stream_exec(
    args: Sequence[str],
    on_stdout: LineHandler,
    on_stderr: LineHandler,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run a long job, passing each output line to the handlers; returns the exit code.

    Cancelling the calling task kills the whole process tree before re-raising.
    """
    if not args or not all(isinstance(a, str) for a in args):
        raise ProcessError("args must be a non-empty list of strings")
    group: dict = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            **group,
        )
    except NotImplementedError as exc:  # pragma: no cover - Windows SelectorEventLoop only
        raise ProcessError(
            "This event loop cannot run subprocesses. On Windows, start the engine without --reload."
        ) from exc
    except OSError as exc:
        raise ProcessError(f"cannot start {args[0]}: {exc}") from exc

    if proc.stdout is None or proc.stderr is None:  # pragma: no cover - PIPE was requested
        raise ProcessError("no output pipes")
    # Shielded, so that cancelling the job does not stop the readers: after the kill they read
    # to end-of-file and the pipes close cleanly.
    pumps = asyncio.ensure_future(
        asyncio.gather(_pump(proc.stdout, on_stdout), _pump(proc.stderr, on_stderr))
    )
    try:
        await asyncio.shield(pumps)
        return await proc.wait()
    except asyncio.CancelledError:
        await _kill_tree(proc)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(pumps, 10)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 10)
        raise
    finally:
        _close_transport(proc)
