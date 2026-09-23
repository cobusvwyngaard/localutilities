"""Snapshots of the exact argument lists each preset generates (CLAUDE.md, DESIGN.md §10)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from werkbank_engine.jobs import ToolError
from werkbank_engine.tools import _convert, audio_compress, download_media, video_compress
from werkbank_engine.tools._ffmpeg import MediaInfo, Stream, parse_probe, progress_handler

SRC, DST = Path("/in/clip.mkv"), Path("/work/0.mp4")
PREFIX = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"]
SCALE_720 = "scale='if(gte(iw,ih),-2,trunc(min(iw,720)/2)*2)':'if(gte(iw,ih),min(ih,720),-2)'"
SCALE_1080 = "scale='if(gte(iw,ih),-2,trunc(min(iw,1080)/2)*2)':'if(gte(iw,ih),min(ih,1080),-2)'"
X264 = ["-preset", "medium", "-pix_fmt", "yuv420p"]
TAIL = ["-map_metadata", "0", "-movflags", "+faststart"]


def single(preset: str, encoder: str | None = None) -> list[str]:
    return video_compress.build_single_pass("ffmpeg", SRC, DST, video_compress.PRESETS[preset], encoder)


def test_share_preset() -> None:
    assert single("share") == [
        *PREFIX, "-i", str(SRC), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-vf", SCALE_720, "-c:v", "libx264", "-crf", "28", *X264,
        "-c:a", "aac", "-b:a", "96k", *TAIL, str(DST),
    ]  # fmt: skip


def test_balanced_preset() -> None:
    assert single("balanced") == [
        *PREFIX, "-i", str(SRC), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-vf", SCALE_1080, "-c:v", "libx264", "-crf", "23", *X264,
        "-c:a", "aac", "-b:a", "128k", *TAIL, str(DST),
    ]  # fmt: skip


def test_archive_preset_uses_hevc_without_scaling() -> None:
    assert single("archive") == [
        *PREFIX, "-i", str(SRC), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-c:v", "libx265", "-crf", "26", "-preset", "medium", "-tag:v", "hvc1",
        "-x265-params", "log-level=error", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", *TAIL, str(DST),
    ]  # fmt: skip


def test_lecture_preset() -> None:
    assert single("lecture") == [
        *PREFIX, "-i", str(SRC), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-vf", f"{SCALE_1080},fps=15", "-c:v", "libx264", "-crf", "28", *X264,
        "-c:a", "aac", "-b:a", "64k", "-ac", "1", *TAIL, str(DST),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("encoder", "expected"),
    [
        ("h264_nvenc", ["-c:v", "h264_nvenc", "-rc", "vbr", "-cq", "23", "-b:v", "0"]),
        ("h264_qsv", ["-c:v", "h264_qsv", "-global_quality", "23"]),
        ("h264_amf", ["-c:v", "h264_amf", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]),
    ],
)
def test_hardware_encoders(encoder: str, expected: list[str]) -> None:
    args = single("balanced", encoder)
    start = args.index("-c:v")
    assert args[start : start + len(expected)] == expected
    assert "libx264" not in args


def test_target_size_math() -> None:
    # 25 MB over 60 s: 25 * 8192 / 60 * 0.97 = 3310.9 kbps in total, minus 96 kbps audio = 3214.9
    assert video_compress.target_video_kbps(25, 60) == 3214
    with pytest.raises(ToolError, match="too small"):
        video_compress.target_video_kbps(1, 3600)


def test_target_size_two_passes() -> None:
    preset = video_compress.PRESETS["target"]
    first, second = video_compress.build_target_passes(
        "ffmpeg", SRC, DST, preset, 3215, Path("/work/pass0"), None
    )
    head = [*PREFIX, "-i", str(SRC), "-map", "0:v:0", "-sn", "-dn", "-vf", SCALE_1080]
    video = ["-c:v", "libx264", "-b:v", "3215k", "-preset", "medium", "-pix_fmt", "yuv420p",
             "-passlogfile", str(Path("/work/pass0"))]  # fmt: skip
    assert first == [*head, *video, "-pass", "1", "-an", "-f", "null", os.devnull]
    assert second == [
        *head,
        "-map",
        "0:a:0?",
        *video,
        "-pass",
        "2",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        *TAIL,
        str(DST),
    ]


def test_target_size_with_hardware_is_one_pass() -> None:
    passes = video_compress.build_target_passes(
        "ffmpeg", SRC, DST, video_compress.PRESETS["target"], 3215, Path("/p"), "h264_nvenc"
    )
    assert len(passes) == 1
    assert "-pass" not in passes[0]
    assert passes[0][passes[0].index("-c:v") + 1 : passes[0].index("-c:v") + 4] == [
        "h264_nvenc",
        "-b:v",
        "3215k",
    ]


@pytest.mark.parametrize(
    ("preset", "codec_args"),
    [
        ("speech", ["-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-application", "voip"]),
        ("speech-mp3", ["-c:a", "libmp3lame", "-b:a", "64k", "-ac", "1"]),
        ("music", ["-c:a", "aac", "-b:a", "192k"]),
        ("music-mp3", ["-c:a", "libmp3lame", "-q:a", "2"]),
    ],
)
def test_audio_presets(preset: str, codec_args: list[str]) -> None:
    args = audio_compress.build_args("ffmpeg", SRC, DST, audio_compress.PRESETS[preset])
    assert args == [*PREFIX, "-i", str(SRC), "-map", "0:a:0", "-vn", "-sn", "-dn", *codec_args,
                    "-map_metadata", "0", str(DST)]  # fmt: skip


def test_podcast_preset_normalises_loudness() -> None:
    args = audio_compress.build_args("ffmpeg", SRC, DST, audio_compress.PRESETS["podcast"])
    assert args[args.index("-af") + 1] == "loudnorm=I=-16:TP=-1.5:LRA=11"
    assert args[args.index("-ar") + 1] == "44100"


def info(video: str | None, audio: str | None, subtitles: bool = False) -> MediaInfo:
    streams = []
    if video:
        streams.append(Stream(0, "video", video))
    if audio:
        streams.append(Stream(1, "audio", audio))
    if subtitles:
        streams.append(Stream(2, "subtitle", "subrip"))
    return MediaInfo(duration=10, streams=tuple(streams))


def test_convert_remuxes_compatible_streams() -> None:
    plan = _convert.plan_video(info("h264", "aac"), "mp4")
    assert plan.args == ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-c:v", "copy", "-c:a", "copy",
                         "-movflags", "+faststart"]  # fmt: skip
    assert _convert.describe(plan) == "No quality loss: streams were copied, not re-encoded."


def test_convert_reencodes_only_what_does_not_fit() -> None:
    plan = _convert.plan_video(info("h264", "vorbis"), "mp4")
    assert "-c:v" in plan.args and plan.args[plan.args.index("-c:v") + 1] == "copy"
    assert plan.args[plan.args.index("-c:a") + 1] == "aac"
    assert _convert.describe(plan) == "Video copied without quality loss; re-encoded audio to AAC."


def test_convert_hevc_into_mp4_gets_the_apple_tag() -> None:
    plan = _convert.plan_video(info("hevc", "aac"), "mp4")
    assert plan.args[plan.args.index("-tag:v") + 1] == "hvc1"


def test_convert_to_webm_reencodes_h264() -> None:
    plan = _convert.plan_video(info("h264", "aac"), "webm")
    assert plan.args[plan.args.index("-c:v") + 1] == "libvpx-vp9"
    assert plan.args[plan.args.index("-c:a") + 1] == "libopus"
    assert _convert.describe(plan).startswith("Re-encoded video to VP9, audio to Opus")


def test_mkv_takes_anything() -> None:
    assert _convert.describe(_convert.plan_video(info("vp9", "opus"), "mkv")).startswith("No quality loss")


@pytest.mark.parametrize(
    ("source", "target", "copied"),
    [("mp3", "mp3", True), ("aac", "m4a", True), ("aac", "mp3", False), ("opus", "opus", True),
     ("pcm_s16le", "flac", False), ("flac", "flac", True), ("vorbis", "ogg", True)],
)  # fmt: skip
def test_audio_convert_plans(source: str, target: str, copied: bool) -> None:
    plan = _convert.plan_audio(info(None, source), target)
    assert (plan.args[plan.args.index("-c:a") + 1] == "copy") is copied


def test_convert_needs_the_right_streams() -> None:
    with pytest.raises(ToolError, match="no video"):
        _convert.plan_video(info(None, "mp3"), "mp4")
    with pytest.raises(ToolError, match="no audio"):
        _convert.plan_audio(info("h264", None), "mp3")


def test_cover_art_is_not_video() -> None:
    parsed = parse_probe({
        "streams": [
            {"index": 0, "codec_type": "audio", "codec_name": "mp3", "disposition": {"attached_pic": 0}},
            {"index": 1, "codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
        ],
        "format": {"duration": "12.5"},
    })  # fmt: skip
    assert parsed.video is None
    assert parsed.audio is not None and parsed.duration == 12.5


def test_ffmpeg_progress_lines() -> None:
    seen: list[float] = []
    handle = progress_handler(10.0, seen.append)
    for line in ("frame=12", "out_time_us=2500000", "out_time_us=N/A", "progress=continue", "progress=end"):
        handle(line)
    assert seen == [0.25, 1.0]


DOWNLOAD_DEFAULTS = {"mode": "video", "quality": "1080", "audioFormat": "m4a", "playlist": False,
                     "subtitles": False, "sponsorblock": False}  # fmt: skip


def test_download_video_arguments() -> None:
    args = download_media.build_args(
        ["python", "-m", "yt_dlp"], "/bin/ffmpeg", "/bin/deno", Path("/work"), "https://example.com/v",
        DOWNLOAD_DEFAULTS, True,
    )  # fmt: skip
    assert args[:3] == ["python", "-m", "yt_dlp"]
    assert args[args.index("-f") + 1] == (
        "bv*[height<=?1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=?1080]+ba/b[height<=?1080]"
    )
    assert args[args.index("--merge-output-format") + 1] == "mp4"
    assert args[args.index("--js-runtimes") + 1] == "deno:/bin/deno"
    assert args[args.index("--ffmpeg-location") + 1] == "/bin/ffmpeg"
    assert "--no-playlist" in args and "--windows-filenames" in args
    for flag in ("--embed-metadata", "--embed-thumbnail", "--embed-chapters", "--ignore-config"):
        assert flag in args
    assert args[-2:] == ["--", "https://example.com/v"]  # the URL can never be read as an option


def test_download_audio_playlist_subtitles_sponsorblock() -> None:
    params = {**DOWNLOAD_DEFAULTS, "mode": "audio", "audioFormat": "mp3", "playlist": True,
              "subtitles": True, "sponsorblock": True}  # fmt: skip
    args = download_media.build_args(
        ["yt-dlp.exe"], "ffmpeg", "deno", Path("/w"), "https://x.test/p", params, False
    )
    assert args[:2] == ["yt-dlp.exe", "--ignore-config"]
    assert args[args.index("-x") + 1 : args.index("-x") + 3] == ["--audio-format", "mp3"]
    assert "--no-playlist" not in args
    assert args[args.index("--sleep-requests") + 1] == "1"
    assert args[args.index("--sub-langs") + 1] == "en.*,af.*"
    assert args[args.index("--sponsorblock-remove") + 1] == "sponsor"
    assert "--windows-filenames" not in args


def test_download_uses_the_standalone_ytdlp_when_bundled() -> None:
    assert download_media.ytdlp_command("C:/Werkbank/bin/yt-dlp.exe") == ["C:/Werkbank/bin/yt-dlp.exe"]
    assert download_media.ytdlp_command(None)[1:] == ["-m", "yt_dlp"]


def test_download_progress_parsing() -> None:
    assert download_media.parse_progress("[werkbank] 500 1000 NA") == 0.5
    assert download_media.parse_progress("[werkbank] 250 NA 1000.0") == 0.25
    assert download_media.parse_progress("[werkbank] 10 NA NA") is None


def test_download_errors_get_a_plain_explanation() -> None:
    raw = "yt-dlp failed: ERROR: [youtube] x: Sign in to confirm you\u2019re not a bot. Use --cookies"
    assert download_media.explain(raw).startswith("YouTube is asking this connection to sign in")
    assert download_media.explain(raw).endswith(raw)
    assert download_media.explain("yt-dlp failed: something else") == "yt-dlp failed: something else"
