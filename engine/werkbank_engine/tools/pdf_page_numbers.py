"""pdf.page-numbers — drawn with reportlab onto each page, upright as the reader sees it."""

from __future__ import annotations

from pathlib import Path

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import MM, open_pdf, per_pdf, save_pdf, stamp_pages

HEAVY = False
MARGIN = 12 * MM
FONT = "Helvetica"


def number_text(style: str, number: int, total: int) -> str:
    return {
        "n": f"{number}",
        "page-n": f"Page {number}",
        "n-of-total": f"{number} of {total}",
        "page-n-of-total": f"Page {number} of {total}",
    }[style]


async def run(ctx: ToolContext) -> None:
    p = ctx.params
    position, style, start, size, skip_first = (
        p["position"],
        p["style"],
        p["start"],
        p["fontSize"],
        p["skipFirst"],
    )

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            pages = list(range(1 if skip_first else 0, len(pdf.pages)))
            total = start + len(pages) - 1

            def draw(canvas, width: float, height: float, index: int) -> None:  # type: ignore[no-untyped-def]
                text = number_text(style, start + pages.index(index), total)
                canvas.setFont(FONT, size)
                vertical, horizontal = position.split("-")
                y = MARGIN - size / 2 if vertical == "bottom" else height - MARGIN
                if horizontal == "left":
                    canvas.drawString(MARGIN, y, text)
                elif horizontal == "right":
                    canvas.drawRightString(width - MARGIN, y, text)
                else:
                    canvas.drawCentredString(width / 2, y, text)

            stamp_pages(pdf, pages, draw, report)
            save_pdf(pdf, dst)
        return f"numbered {len(pages)} page(s)."

    await per_pdf(ctx, "Numbering", "numbered", ".pdf", work)
