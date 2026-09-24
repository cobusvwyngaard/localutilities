"""audio.transcribe — speech to text with whisper.cpp (DESIGN.md §4.2).

FFmpeg turns any audio or video into 16 kHz mono WAV; whisper-cli transcribes it with the chosen
model and Silero voice activity detection (skips silence, which also stops Whisper from inventing
text during long pauses; timestamps stay on the original timeline).

Models live in the portable app's bin/models (runtime.models_dir); nothing is downloaded.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from werkbank_engine.files import output_name
from werkbank_engine.jobs import ToolContext, ToolError
from werkbank_engine.runtime import models_dir
from werkbank_engine.tools._ffmpeg import ffmpeg_prefix, probe, run_ffmpeg

HEAVY = True

MODELS = {
    "small": "ggml-small-q5_1.bin",
    "turbo": "ggml-large-v3-turbo-q5_0.bin",
}
VAD_MODEL = "ggml-silero-v6.2.0.bin"
FORMATS = {
    "txt": ("txt",),
    "srt": ("srt",),
    "vtt": ("vtt",),
    "all": ("txt", "srt", "vtt"),
}
PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")
# Share of the job spent converting the audio; whisper gets the rest.
CONVERT_SPAN = 0.05


def model_path(name: str) -> Path:
    folder = models_dir()
    path = folder / MODELS[name] if folder else None
    if path is None or not path.is_file():
        raise ToolError(
            f"The speech model file {MODELS[name]} is missing. "
            "Download the Werkbank portable app again and extract the whole zip file."
        )
    return path


def vad_path() -> Path | None:
    folder = models_dir()
    path = folder / VAD_MODEL if folder else None
    return path if path and path.is_file() else None


def thread_count() -> int:
    """Leave one core for the rest of the laptop; whisper.cpp gains little beyond 8 threads."""
    return max(1, min((os.cpu_count() or 4) - 1, 8))


def build_args(
    whisper: str,
    model: Path,
    vad: Path | None,
    wav: Path,
    out_base: Path,
    language: str,
    formats: tuple[str, ...],
) -> list[str]:
    args = [
        whisper,
        "-m", str(model),
        "-f", str(wav),
        "-l", language,
        "-t", str(thread_count()),
        "-of", str(out_base),
        "-pp",  # progress on stderr
        "-np",  # nothing else but results and progress
    ]  # fmt: skip
    args += [f"-o{fmt}" for fmt in formats]
    if vad is not None:
        args += ["--vad", "-vm", str(vad)]
    return args


def parse_progress(line: str) -> float | None:
    match = PROGRESS_RE.search(line)
    return int(match.group(1)) / 100 if match else None


async def run(ctx: ToolContext) -> None:
    whisper = ctx.program("whisper")
    ffmpeg = ctx.program("ffmpeg")
    model = model_path(ctx.params["model"])
    vad = vad_path()
    formats = FORMATS[ctx.params["format"]]
    language = ctx.params["language"]
    count = len(ctx.inputs)

    for i, item in enumerate(ctx.inputs):
        src = item.path
        if src is None:  # pragma: no cover - this tool only accepts files
            raise ToolError("expected a file")
        base, span = i / count, 1 / count
        label = f" ({i + 1} of {count})" if count > 1 else ""
        info = await probe(ctx, src)
        if info.audio is None:
            raise ToolError(f"{item.name} has no audio to transcribe.")

        wav = ctx.work / f"{i}.wav"
        await run_ffmpeg(
            ctx,
            [
                *ffmpeg_prefix(ffmpeg),
                "-i",
                str(src),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            info.duration,
            base,
            span * CONVERT_SPAN,
            f"Preparing the audio of {item.name}{label}",
        )

        out_base = ctx.work / f"{i}-transcript"
        message = f"Transcribing {item.name}{label}"
        ctx.progress(base + span * CONVERT_SPAN, message)

        def on_stderr(line: str, base: float = base, span: float = span, message: str = message) -> None:
            fraction = parse_progress(line)
            if fraction is not None:
                ctx.progress(base + span * (CONVERT_SPAN + (1 - CONVERT_SPAN) * fraction), message)

        await ctx.run(
            build_args(whisper, model, vad, wav, out_base, language, formats),
            on_stderr=on_stderr,
            what="whisper.cpp",
        )
        # whisper-cli exits with 0 even when it could not read the audio: check the results.
        produced = [(fmt, out_base.with_suffix(f".{fmt}")) for fmt in formats]
        missing = [fmt for fmt, path in produced if not path.is_file()]
        if missing:
            detail = "\n".join(list(ctx.job.log)[-5:])
            raise ToolError(f"whisper.cpp did not produce a transcript for {item.name}.\n{detail}")
        text = produced[0][1].read_text(encoding="utf-8", errors="replace").strip()
        words = len(text.split()) if formats[0] == "txt" else None
        for fmt, path in produced:
            ctx.add_output(path, output_name(item.name, "transcript", f".{fmt}"))
        detected = "" if language != "auto" else " (language detected automatically)"
        ctx.note(
            f"{item.name}: transcribed{detected}"
            + (f", {words} words" if words is not None else "")
            + ("" if text else ". No speech was found.")
        )
