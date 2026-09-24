"""Shared FFmpeg helpers: probing, progress parsing and the argument-list prefix."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from werkbank_engine.jobs import ToolContext, ToolError
from werkbank_engine.procs import ProcessError, run_exec


@dataclass(frozen=True)
class Stream:
    index: int
    kind: str  # "video", "audio", "subtitle", ...
    codec: str
    width: int | None = None
    height: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class MediaInfo:
    duration: float | None
    streams: tuple[Stream, ...]

    @property
    def video(self) -> Stream | None:
        return next((s for s in self.streams if s.kind == "video"), None)

    @property
    def audio(self) -> Stream | None:
        return next((s for s in self.streams if s.kind == "audio"), None)

    @property
    def has_subtitles(self) -> bool:
        return any(s.kind == "subtitle" for s in self.streams)


def parse_probe(data: dict) -> MediaInfo:
    streams = []
    for s in data.get("streams", []):
        kind = s.get("codec_type", "other")
        if kind == "video" and s.get("disposition", {}).get("attached_pic"):
            kind = "cover"  # album art is not a video stream
        streams.append(
            Stream(
                index=int(s.get("index", 0)),
                kind=kind,
                codec=s.get("codec_name", "unknown"),
                width=s.get("width"),
                height=s.get("height"),
                channels=s.get("channels"),
            )
        )
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return MediaInfo(duration=duration if duration and duration > 0 else None, streams=tuple(streams))


async def probe(ctx: ToolContext, path: Path) -> MediaInfo:
    args = [
        ctx.program("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,channels:stream_disposition=attached_pic",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = await run_exec(args, limit_seconds=60)
    except ProcessError as exc:
        raise ToolError(f"Could not read {path.name}: {exc}") from exc
    if result.returncode != 0:
        raise ToolError(f"Could not read {path.name}: {result.stderr.strip() or 'not a media file'}")
    return parse_probe(json.loads(result.stdout or "{}"))


def ffmpeg_prefix(ffmpeg: str) -> list[str]:
    """Global options: quiet, machine-readable progress on stdout, never prompt."""
    return [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"]


def progress_handler(duration: float | None, report: Callable[[float], None]) -> Callable[[str], None]:
    """Turns `-progress pipe:1` lines (`out_time_us=…`) into a 0..1 fraction."""

    def handle(line: str) -> None:
        key, _, value = line.partition("=")
        if key == "out_time_us" and duration:
            with contextlib.suppress(ValueError):
                report(int(value) / 1_000_000 / duration)
        elif key == "progress" and value == "end":
            report(1.0)

    return handle


def scale_short_side(limit: int) -> str:
    """Scale so the shorter side is at most `limit` px, keeping aspect ratio and even sizes."""
    return f"scale='if(gte(iw,ih),-2,trunc(min(iw,{limit})/2)*2)':'if(gte(iw,ih),min(ih,{limit}),-2)'"


async def run_ffmpeg(
    ctx: ToolContext,
    args: Sequence[str],
    duration: float | None,
    start: float,
    span: float,
    message: str,
) -> None:
    """Run ffmpeg, mapping its progress into the job's [start, start + span] range."""
    ctx.progress(start, message)
    await ctx.run(
        list(args),
        on_stdout=progress_handler(duration, lambda f: ctx.progress(start + span * min(f, 1.0))),
        what="FFmpeg",
    )


def describe_size_change(before: int, after: int) -> str:
    small = max(before, after) < 1_048_576

    def mb(n: int) -> str:
        return f"{n / 1024:.0f} KB" if small else f"{n / 1_048_576:.1f} MB"

    if before <= 0:
        return mb(after)
    change = (after - before) / before * 100
    return f"{mb(before)} → {mb(after)} ({change:+.0f} %)"
