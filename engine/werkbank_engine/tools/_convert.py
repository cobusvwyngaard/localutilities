"""Remux-first conversion (DESIGN.md §5.3): copy every stream the target container accepts,
re-encode only the ones it does not, and say which happened."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from werkbank_engine.files import output_name
from werkbank_engine.jobs import ToolContext, ToolError
from werkbank_engine.tools._ffmpeg import MediaInfo, ffmpeg_prefix, probe, run_ffmpeg

ANY = frozenset({"*"})

# Codecs each target container can hold as they are (conservative: what common players accept).
VIDEO_COPY = {
    "mp4": frozenset({"h264", "hevc", "av1", "mpeg4"}),
    "mov": frozenset({"h264", "hevc", "mpeg4", "prores", "mjpeg"}),
    "mkv": ANY,
    "webm": frozenset({"vp8", "vp9", "av1"}),
}
AUDIO_COPY = {
    "mp4": frozenset({"aac", "mp3", "ac3", "eac3", "alac"}),
    "mov": frozenset({"aac", "mp3", "alac", "ac3", "pcm_s16le", "pcm_s24le"}),
    "mkv": ANY,
    "webm": frozenset({"opus", "vorbis"}),
    "mp3": frozenset({"mp3"}),
    "m4a": frozenset({"aac", "alac"}),
    "opus": frozenset({"opus"}),
    "ogg": frozenset({"vorbis"}),
    "flac": frozenset({"flac"}),
    "wav": frozenset({"pcm_s16le", "pcm_s24le", "pcm_f32le"}),
}
# Re-encoding when a copy is not possible: the Balanced preset for video (§5.3).
VIDEO_ENCODE = {
    "mp4": ("-c:v", "libx264", "-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p"),
    "mov": ("-c:v", "libx264", "-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p"),
    "mkv": ("-c:v", "libx264", "-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p"),
    "webm": ("-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-cpu-used", "4"),
}
AUDIO_ENCODE = {
    "mp4": ("-c:a", "aac", "-b:a", "160k"),
    "mov": ("-c:a", "aac", "-b:a", "160k"),
    "mkv": ("-c:a", "aac", "-b:a", "160k"),
    "webm": ("-c:a", "libopus", "-b:a", "128k"),
    "mp3": ("-c:a", "libmp3lame", "-q:a", "2"),
    "m4a": ("-c:a", "aac", "-b:a", "192k"),
    "opus": ("-c:a", "libopus", "-b:a", "128k"),
    "ogg": ("-c:a", "libvorbis", "-q:a", "5"),
    "flac": ("-c:a", "flac"),
    "wav": ("-c:a", "pcm_s16le"),
}
CODEC_NAMES = {"libx264": "H.264", "libvpx-vp9": "VP9", "aac": "AAC", "libopus": "Opus", "libmp3lame": "MP3",
               "libvorbis": "Vorbis", "flac": "FLAC", "pcm_s16le": "PCM"}  # fmt: skip


def _can_copy(table: dict[str, frozenset[str]], target: str, codec: str) -> bool:
    allowed = table[target]
    return allowed is ANY or codec in allowed


@dataclass
class Plan:
    args: list[str] = field(default_factory=list)
    copied: list[str] = field(default_factory=list)  # "video", "audio"
    encoded: list[str] = field(default_factory=list)  # "video to H.264", ...


def plan_video(info: MediaInfo, target: str) -> Plan:
    video, audio = info.video, info.audio
    if video is None:
        raise ToolError("no video stream (use Convert audio for sound-only files)")
    plan = Plan(args=["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"])
    if _can_copy(VIDEO_COPY, target, video.codec):
        plan.args += ["-c:v", "copy"]
        if video.codec == "hevc" and target in ("mp4", "mov"):
            plan.args += ["-tag:v", "hvc1"]  # lets Apple devices play copied HEVC
        plan.copied.append("video")
    else:
        encode = VIDEO_ENCODE[target]
        plan.args += list(encode)
        plan.encoded.append(f"video to {CODEC_NAMES[encode[1]]}")
    if audio is not None:
        if _can_copy(AUDIO_COPY, target, audio.codec):
            plan.args += ["-c:a", "copy"]
            plan.copied.append("audio")
        else:
            encode = AUDIO_ENCODE[target]
            plan.args += list(encode)
            plan.encoded.append(f"audio to {CODEC_NAMES[encode[1]]}")
    if target in ("mp4", "mov"):
        plan.args += ["-movflags", "+faststart"]
    return plan


def plan_audio(info: MediaInfo, target: str) -> Plan:
    audio = info.audio
    if audio is None:
        raise ToolError("no audio")
    plan = Plan(args=["-map", "0:a:0", "-vn", "-sn", "-dn"])
    if _can_copy(AUDIO_COPY, target, audio.codec):
        plan.args += ["-c:a", "copy"]
        plan.copied.append("audio")
    else:
        encode = AUDIO_ENCODE[target]
        plan.args += list(encode)
        plan.encoded.append(f"audio to {CODEC_NAMES[encode[1]]}")
    return plan


def describe(plan: Plan) -> str:
    if not plan.encoded:
        return "No quality loss: streams were copied, not re-encoded."
    if plan.copied:
        copied = " and ".join(plan.copied).capitalize()
        return f"{copied} copied without quality loss; re-encoded {', '.join(plan.encoded)}."
    return f"Re-encoded {', '.join(plan.encoded)} (the source codecs do not fit this format)."


def build_args(ffmpeg: str, src: Path, dst: Path, plan: Plan) -> list[str]:
    return [*ffmpeg_prefix(ffmpeg), "-i", str(src), *plan.args, "-map_metadata", "0", str(dst)]


async def convert(ctx: ToolContext, video: bool) -> None:
    ffmpeg = ctx.program("ffmpeg")
    target = ctx.params["target"]
    extension = f".{target}"
    count = len(ctx.inputs)
    for i, item in enumerate(ctx.inputs):
        src = item.path
        if src is None:  # pragma: no cover - these tools only accept files
            raise ToolError("expected a file")
        info = await probe(ctx, src)
        try:
            plan = plan_video(info, target) if video else plan_audio(info, target)
        except ToolError as exc:
            raise ToolError(f"{item.name}: {exc}") from exc
        dst = ctx.work / f"{i}{extension}"
        label = f"Converting {item.name}" + (f" ({i + 1} of {count})" if count > 1 else "")
        await run_ffmpeg(ctx, build_args(ffmpeg, src, dst, plan), info.duration, i / count, 1 / count, label)
        notes = [describe(plan)]
        if video and info.has_subtitles:
            notes.append("Subtitles were not carried over.")
        ctx.note(f"{item.name}: {' '.join(notes)}")
        ctx.add_output(dst, output_name(item.name, "converted", extension))
