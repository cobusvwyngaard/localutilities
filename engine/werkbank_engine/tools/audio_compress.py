"""audio.compress — speech, podcast and music presets (DESIGN.md §5.2); also takes videos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from werkbank_engine.files import output_name
from werkbank_engine.jobs import ToolContext, ToolError
from werkbank_engine.tools._ffmpeg import describe_size_change, ffmpeg_prefix, probe, run_ffmpeg

HEAVY = False


@dataclass(frozen=True)
class AudioPreset:
    extension: str
    codec: tuple[str, ...]
    filters: str | None = None


PRESETS = {
    "speech": AudioPreset(".opus", ("-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-application", "voip")),
    "speech-mp3": AudioPreset(".mp3", ("-c:a", "libmp3lame", "-b:a", "64k", "-ac", "1")),
    # loudnorm resamples internally to 192 kHz, so set the output rate explicitly.
    "podcast": AudioPreset(
        ".mp3",
        ("-c:a", "libmp3lame", "-b:a", "96k", "-ac", "1", "-ar", "44100"),
        "loudnorm=I=-16:TP=-1.5:LRA=11",
    ),
    "music": AudioPreset(".m4a", ("-c:a", "aac", "-b:a", "192k")),
    "music-mp3": AudioPreset(".mp3", ("-c:a", "libmp3lame", "-q:a", "2")),
}


def build_args(ffmpeg: str, src: Path, dst: Path, preset: AudioPreset) -> list[str]:
    filters = ["-af", preset.filters] if preset.filters else []
    return [
        *ffmpeg_prefix(ffmpeg),
        "-i", str(src),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        *filters,
        *preset.codec,
        "-map_metadata", "0",
        str(dst),
    ]  # fmt: skip


async def run(ctx: ToolContext) -> None:
    ffmpeg = ctx.program("ffmpeg")
    preset = PRESETS[ctx.params["preset"]]
    count = len(ctx.inputs)
    for i, item in enumerate(ctx.inputs):
        src = item.path
        if src is None:  # pragma: no cover - this tool only accepts files
            raise ToolError("expected a file")
        info = await probe(ctx, src)
        if info.audio is None:
            raise ToolError(f"{item.name} has no audio.")
        dst = ctx.work / f"{i}{preset.extension}"
        label = f"Compressing {item.name}" + (f" ({i + 1} of {count})" if count > 1 else "")
        args = build_args(ffmpeg, src, dst, preset)
        await run_ffmpeg(ctx, args, info.duration, i / count, 1 / count, label)
        ctx.note(f"{item.name}: {describe_size_change(src.stat().st_size, dst.stat().st_size)}")
        ctx.add_output(dst, output_name(item.name, "compressed", preset.extension))
