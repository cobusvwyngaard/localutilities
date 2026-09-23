"""Engine tool implementations, keyed by registry id (packages/shared/src/tools.ts).

Each module has `HEAVY` (queue class, DESIGN.md §3.2) and `async def run(ctx: ToolContext)`.
"""

from types import ModuleType

from werkbank_engine.tools import (
    audio_compress,
    audio_convert,
    download_media,
    pdf_unlock,
    video_compress,
    video_convert,
)

IMPLEMENTATIONS: dict[str, ModuleType] = {
    "audio.compress": audio_compress,
    "audio.convert": audio_convert,
    "download.media": download_media,
    "pdf.unlock": pdf_unlock,
    "video.compress": video_compress,
    "video.convert": video_convert,
}
