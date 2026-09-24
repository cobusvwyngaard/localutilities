"""pdf.crop — shrink the crop box (lossless: the cut-off content stays in the file but is hidden).

Margins are given as the reader sees the page, so rotated pages map them to the right edges."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import MM, open_pdf, parse_pages, per_pdf, save_pdf

HEAVY = False
MIN_SIDE = 36.0  # half an inch must remain


def unrotated_margins(
    rotation: int, top: float, bottom: float, left: float, right: float
) -> tuple[float, ...]:
    """Display margins → (left, bottom, right, top) of the unrotated page for /Rotate 0/90/180/270."""
    return {
        0: (left, bottom, right, top),
        90: (top, left, bottom, right),
        180: (right, top, left, bottom),
        270: (bottom, right, top, left),
    }[rotation % 360]


async def run(ctx: ToolContext) -> None:
    p = ctx.params
    top, bottom, left, right = (p[k] * MM for k in ("top", "bottom", "left", "right"))
    spec = p["pages"]

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            pages = sorted(set(parse_pages(spec, len(pdf.pages))))
            for i in pages:
                page = pdf.pages[i]
                x0, y0, x1, y1 = (float(v) for v in page.cropbox)
                ml, mb, mr, mt = unrotated_margins(page.rotation, top, bottom, left, right)
                box = (x0 + ml, y0 + mb, x1 - mr, y1 - mt)
                if box[2] - box[0] < MIN_SIDE or box[3] - box[1] < MIN_SIDE:
                    raise ToolError(f"The margins are larger than page {i + 1}.")
                page.obj.CropBox = pikepdf.Array(box)
            save_pdf(pdf, dst)
        return f"cropped {len(pages)} page(s). No quality loss."

    await per_pdf(ctx, "Cropping", "cropped", ".pdf", work)
