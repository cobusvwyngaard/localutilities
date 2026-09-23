"""audio.convert — MP3/M4A/Opus/OGG/FLAC/WAV, copying the audio when the format allows (§5.3)."""

from werkbank_engine.jobs import ToolContext
from werkbank_engine.tools._convert import convert

HEAVY = False


async def run(ctx: ToolContext) -> None:
    await convert(ctx, video=False)
