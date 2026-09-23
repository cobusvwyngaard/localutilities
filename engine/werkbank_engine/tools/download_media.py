"""download.media — yt-dlp with Deno (DESIGN.md §5.1). yt-dlp runs as `python -m yt_dlp` in the
engine's own environment, with FFmpeg and Deno passed explicitly (PATH may be stale on Windows)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from werkbank_engine.files import safe_filename
from werkbank_engine.jobs import ToolContext, ToolError

HEAVY = False
PROGRESS_TAG = "[werkbank]"
# Temporary or already-embedded files that are not results.
LEFTOVER_SUFFIXES = {".part", ".ytdl", ".temp", ".webp", ".jpg", ".jpeg", ".png"}

# DESIGN.md §5.1, with `<=?` so formats whose height is unknown are not rejected outright.
VIDEO_FORMATS = {
    "best": "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*+ba/b",
    **{
        h: f"bv*[height<=?{h}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=?{h}]+ba/b[height<=?{h}]"
        for h in ("1080", "720", "480")
    },
}

STAGES = {
    "[Merger]": "Merging video and audio",
    "[ExtractAudio]": "Extracting audio",
    "[EmbedThumbnail]": "Adding the thumbnail",
    "[Metadata]": "Adding metadata",
    "[SponsorBlock]": "Finding sponsor segments",
    "[ModifyChapters]": "Cutting sponsor segments",
    "[SubtitlesConvertor]": "Converting subtitles",
}


def build_args(
    python: str, ffmpeg: str, deno: str | None, work: Path, url: str, params: dict, windows: bool
) -> list[str]:
    args = [
        python, "-m", "yt_dlp",
        "--ignore-config", "--no-color", "--newline", "--no-mtime",
        "--progress-template", f"download:{PROGRESS_TAG} %(progress.downloaded_bytes)s "
        "%(progress.total_bytes)s %(progress.total_bytes_estimate)s",
        "--ffmpeg-location", ffmpeg,
        "-P", str(work),
        "-o", "%(title)s [%(id)s].%(ext)s",
        "--embed-metadata", "--embed-thumbnail", "--embed-chapters",
    ]  # fmt: skip
    if deno:
        args += ["--js-runtimes", f"deno:{deno}"]
    if windows:
        args.append("--windows-filenames")
    if params["mode"] == "audio":
        args += ["-f", "ba/b", "-x", "--audio-format", params["audioFormat"]]
    else:
        args += ["-f", VIDEO_FORMATS[params["quality"]], "--merge-output-format", "mp4"]
    if params["playlist"]:
        args += ["--yes-playlist", "--sleep-requests", "1"]
    else:
        args.append("--no-playlist")
    if params["subtitles"]:
        args += ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*,af.*", "--convert-subs", "srt"]
    if params["sponsorblock"]:
        args += ["--sponsorblock-remove", "sponsor"]
    return [*args, "--", url]


HINTS = (
    (
        "not a bot",  # YouTube: "Sign in to confirm you\u2019re not a bot"
        "YouTube is asking this connection to sign in (it does this to some networks, especially VPNs "
        "and cloud servers). Try again later or on another connection.",
    ),
    ("Unsupported URL", "yt-dlp does not know how to download from this address."),
    ("Video unavailable", "The video is unavailable (removed, private or blocked in your country)."),
)


def explain(error: str) -> str:
    """Put a plain-language explanation in front of yt-dlp's own error text."""
    for needle, hint in HINTS:
        if needle.lower() in error.lower():
            return f"{hint}\n\n{error}"
    return error


def parse_progress(line: str) -> float | None:
    """`[werkbank] <downloaded> <total> <estimate>` → fraction (values may be NA)."""
    parts = line[len(PROGRESS_TAG) :].split()
    if len(parts) != 3:
        return None
    downloaded, total, estimate = parts
    try:
        size = float(total) if total not in ("NA", "None") else float(estimate)
        return float(downloaded) / size if size > 0 else None
    except ValueError:
        return None


async def run(ctx: ToolContext) -> None:
    url = ctx.inputs[0].url
    if url is None:  # pragma: no cover - this tool only accepts URLs
        raise ToolError("expected a web address")
    ffmpeg = ctx.program("ffmpeg")
    deno = ctx.program("deno")
    args = build_args(sys.executable, ffmpeg, deno, ctx.work, url, ctx.params, windows=os.name == "nt")
    # Tools yt-dlp starts on its own find FFmpeg and Deno on PATH too.
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(Path(ffmpeg).parent), str(Path(deno).parent), env.get("PATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"

    def on_stdout(line: str) -> None:
        if line.startswith(PROGRESS_TAG):
            fraction = parse_progress(line)
            if fraction is not None:
                ctx.progress(fraction * 0.95)
            return
        ctx.log(line)
        if line.startswith("[download] Destination:"):
            ctx.progress(ctx.job.progress, "Downloading " + Path(line.split(":", 1)[1].strip()).name)
        for tag, message in STAGES.items():
            if line.startswith(tag):
                ctx.progress(0.96, message)

    ctx.progress(None, "Contacting the site")
    try:
        await ctx.run(args, on_stdout=on_stdout, env=env, what="yt-dlp")
    except ToolError as exc:
        raise ToolError(explain(str(exc))) from None

    results = sorted(
        p for p in ctx.work.iterdir() if p.is_file() and p.suffix.lower() not in LEFTOVER_SUFFIXES
    )
    if not results:
        raise ToolError("yt-dlp finished without producing a file.")
    for path in results:
        ctx.add_output(path, safe_filename(path.name))
    ctx.note(f"Downloaded {len(results)} file{'s' if len(results) != 1 else ''}.")
