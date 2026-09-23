"""Running external programs. Argument lists only — never a shell, never a command string."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass


class ProcessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(Exception):  # drain the pipes so the transport can close
        await asyncio.wait_for(proc.communicate(), 5)
    await asyncio.sleep(0)


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
    # asyncio closes a finished subprocess transport one loop iteration later; let it happen now,
    # so no transport outlives a short-lived event loop.
    await asyncio.sleep(0)
    return ExecResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )
