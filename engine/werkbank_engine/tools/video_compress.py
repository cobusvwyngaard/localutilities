"""video.compress — presets from DESIGN.md §5.2, target size (two-pass), optional hardware encoders."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from werkbank_engine.files import output_name
from werkbank_engine.jobs import ToolContext, ToolError
from werkbank_engine.tools._ffmpeg import (
    MediaInfo,
    describe_size_change,
    ffmpeg_prefix,
    probe,
    run_ffmpeg,
    scale_short_side,
)

HEAVY = True
AUDIO_KBPS_TARGET = 96
TARGET_MARGIN = 0.97  # DESIGN.md §5.2: 3 % safety margin

HARDWARE = {
    "h264": ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"),
    "hevc": ("hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_videotoolbox"),
}


@dataclass(frozen=True)
class Preset:
    codec: str  # "h264" or "hevc"
    crf: int
    max_short_side: int | None
    audio: tuple[str, ...]
    fps: int | None = None


PRESETS = {
    "share": Preset("h264", 28, 720, ("-c:a", "aac", "-b:a", "96k")),
    "balanced": Preset("h264", 23, 1080, ("-c:a", "aac", "-b:a", "128k")),
    "archive": Preset("hevc", 26, None, ("-c:a", "aac", "-b:a", "128k")),
    "lecture": Preset("h264", 28, 1080, ("-c:a", "aac", "-b:a", "64k", "-ac", "1"), fps=15),
    "target": Preset("h264", 23, 1080, ("-c:a", "aac", "-b:a", f"{AUDIO_KBPS_TARGET}k")),
}


def video_filters(preset: Preset) -> list[str]:
    filters = []
    if preset.max_short_side:
        filters.append(scale_short_side(preset.max_short_side))
    if preset.fps:
        filters.append(f"fps={preset.fps}")
    return ["-vf", ",".join(filters)] if filters else []


def quality_args(codec: str, crf: int, encoder: str | None) -> list[str]:
    """Constant-quality settings for software x264/x265 or a hardware encoder."""
    if encoder is None:
        if codec == "hevc":
            return ["-c:v", "libx265", "-crf", str(crf), "-preset", "medium", "-tag:v", "hvc1",
                    "-x265-params", "log-level=error", "-pix_fmt", "yuv420p"]  # fmt: skip
        return ["-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"]
    args = ["-c:v", encoder]
    if encoder.endswith("_nvenc"):
        args += ["-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    elif encoder.endswith("_qsv"):
        args += ["-global_quality", str(crf)]
    elif encoder.endswith("_amf"):
        args += ["-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
    elif encoder.endswith("_videotoolbox"):
        args += ["-q:v", "60"]
    if codec == "hevc":
        args += ["-tag:v", "hvc1"]
    return args


def common_tail(preset: Preset) -> list[str]:
    return [*preset.audio, "-map_metadata", "0", "-movflags", "+faststart"]


def build_single_pass(ffmpeg: str, src: Path, dst: Path, preset: Preset, encoder: str | None) -> list[str]:
    return [
        *ffmpeg_prefix(ffmpeg),
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        *video_filters(preset),
        *quality_args(preset.codec, preset.crf, encoder),
        *common_tail(preset),
        str(dst),
    ]  # fmt: skip


def target_video_kbps(target_mb: float, duration: float, audio_kbps: int = AUDIO_KBPS_TARGET) -> int:
    """DESIGN.md §5.2: video_kbps = target_MB * 8192 / duration_s - audio_kbps, with a 3 % margin."""
    total_kbps = target_mb * 8192 / duration * TARGET_MARGIN
    video_kbps = int(total_kbps - audio_kbps)
    if video_kbps < 50:
        raise ToolError(
            f"{target_mb:g} MB is too small for {duration / 60:.0f} minutes of video. Choose a larger target."
        )
    return video_kbps


def build_target_passes(
    ffmpeg: str, src: Path, dst: Path, preset: Preset, kbps: int, passlog: Path, encoder: str | None
) -> list[list[str]]:
    head = [*ffmpeg_prefix(ffmpeg), "-i", str(src), "-map", "0:v:0", "-sn", "-dn", *video_filters(preset)]
    if encoder is not None:  # hardware encoders: one pass at the average bitrate
        hardware = ["-map", "0:a:0?", "-c:v", encoder, "-b:v", f"{kbps}k"]
        return [[*head, *hardware, *common_tail(preset), str(dst)]]
    video = ["-c:v", "libx264", "-b:v", f"{kbps}k", "-preset", "medium", "-pix_fmt", "yuv420p",
             "-passlogfile", str(passlog)]  # fmt: skip
    first = [*head, *video, "-pass", "1", "-an", "-f", "null", os.devnull]
    second = [*head, "-map", "0:a:0?", *video, "-pass", "2", *common_tail(preset), str(dst)]
    return [first, second]


async def choose_encoder(ctx: ToolContext, codec: str) -> str | None:
    if not ctx.params["hardware"]:
        return None
    usable = await ctx.usable_hardware_encoders()
    encoder = next((e for e in HARDWARE[codec] if e in usable), None)
    if encoder is None:
        ctx.note("No usable hardware encoder on this computer: used software encoding instead.")
    return encoder


async def run(ctx: ToolContext) -> None:
    ffmpeg = ctx.program("ffmpeg")
    preset = PRESETS[ctx.params["preset"]]
    encoder = await choose_encoder(ctx, preset.codec)
    if encoder:
        ctx.note(f"Hardware encoder: {encoder}")
    count = len(ctx.inputs)
    for i, item in enumerate(ctx.inputs):
        src = item.path
        if src is None:  # pragma: no cover - this tool only accepts files
            raise ToolError("expected a file")
        info: MediaInfo = await probe(ctx, src)
        if info.video is None:
            raise ToolError(f"{item.name} has no video stream.")
        dst = ctx.work / f"{i}.mp4"
        label = f"Compressing {item.name}" + (f" ({i + 1} of {count})" if count > 1 else "")
        if ctx.params["preset"] == "target":
            if not info.duration:
                raise ToolError(f"Cannot tell how long {item.name} is, so a target size is not possible.")
            kbps = target_video_kbps(ctx.params["targetMb"], info.duration)
            passes = build_target_passes(ffmpeg, src, dst, preset, kbps, ctx.work / f"pass{i}", encoder)
            for p, args in enumerate(passes):
                step = f"{label} — pass {p + 1} of {len(passes)}" if len(passes) > 1 else label
                await run_ffmpeg(ctx, args, info.duration, (i + p / len(passes)) / count,
                                 1 / count / len(passes), step)  # fmt: skip
        else:
            args = build_single_pass(ffmpeg, src, dst, preset, encoder)
            await run_ffmpeg(ctx, args, info.duration, i / count, 1 / count, label)
        ctx.note(f"{item.name}: {describe_size_change(src.stat().st_size, dst.stat().st_size)}")
        ctx.add_output(dst, output_name(item.name, "compressed", ".mp4"))
