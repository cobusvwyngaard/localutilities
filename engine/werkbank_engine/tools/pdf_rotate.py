"""pdf.rotate — turn all or selected pages (lossless: only the page's /Rotate changes)."""

from __future__ import annotations

from pathlib import Path

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import open_pdf, parse_pages, per_pdf, save_pdf

HEAVY = False


async def run(ctx: ToolContext) -> None:
    angle, spec = int(ctx.params["angle"]), ctx.params["pages"]

    def rotate(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            pages = sorted(set(parse_pages(spec, len(pdf.pages))))
            for i in pages:
                pdf.pages[i].rotate(angle, relative=True)
            save_pdf(pdf, dst)
        return f"rotated {len(pages)} page(s). No quality loss."

    await per_pdf(ctx, "Rotating", "rotated", ".pdf", rotate)
