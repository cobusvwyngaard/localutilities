"""pdf.watermark — semi-transparent text across or on top of the pages (reportlab overlay)."""

from __future__ import annotations

import math
from pathlib import Path

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import MM, open_pdf, parse_pages, per_pdf, save_pdf, stamp_pages

HEAVY = False
FONT = "Helvetica-Bold"
MARGIN = 12 * MM


def fit_size(text: str, wanted: float, available: float) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    width = stringWidth(text, FONT, wanted)
    return wanted if width <= available else max(6.0, wanted * available / width)


async def run(ctx: ToolContext) -> None:
    p = ctx.params
    text = p["text"].strip()
    if not text:
        raise ToolError("Enter the watermark text.")
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise ToolError("The watermark text can only use Latin letters, digits and common symbols.") from None
    placement, opacity, wanted, spec = p["placement"], p["opacity"] / 100, p["fontSize"], p["pages"]

    def draw(canvas, width: float, height: float, index: int) -> None:  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFillColorRGB(0.8, 0.1, 0.1)
        canvas.setFillAlpha(opacity)
        if placement == "diagonal":
            angle = math.degrees(math.atan2(height, width))
            size = fit_size(text, wanted, math.hypot(width, height) * 0.8)
            canvas.translate(width / 2, height / 2)
            canvas.rotate(angle)
            canvas.setFont(FONT, size)
            canvas.drawCentredString(0, -size / 3, text)
        else:
            size = fit_size(text, wanted, width - 2 * MARGIN)
            canvas.setFont(FONT, size)
            y = height - MARGIN - size * 0.8 if placement == "top" else MARGIN
            canvas.drawCentredString(width / 2, y, text)
        canvas.restoreState()

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            pages = sorted(set(parse_pages(spec, len(pdf.pages))))
            stamp_pages(pdf, pages, draw, report)
            save_pdf(pdf, dst)
        return f"watermarked {len(pages)} page(s)."

    await per_pdf(ctx, "Watermarking", "watermarked", ".pdf", work)
