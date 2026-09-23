"""video.convert — MP4/MKV/WebM/MOV, remux first (DESIGN.md §5.3)."""

from werkbank_engine.jobs import ToolContext
from werkbank_engine.tools._convert import convert

HEAVY = True  # may have to re-encode video


async def run(ctx: ToolContext) -> None:
    await convert(ctx, video=True)
