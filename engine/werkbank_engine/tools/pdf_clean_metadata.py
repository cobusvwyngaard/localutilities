"""pdf.clean-metadata — remove the document information dictionary, XMP and page-piece data."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import open_pdf, per_pdf, save_pdf

HEAVY = False


def clean(pdf: pikepdf.Pdf) -> list[str]:
    removed = []
    info = pdf.trailer.get("/Info")
    if info is not None and len(info.keys()):
        removed.append(", ".join(str(k).lstrip("/") for k in info.keys()))  # noqa: SIM118 - pikepdf Dictionary
    if "/Info" in pdf.trailer:
        del pdf.trailer["/Info"]
    for key in ("/Metadata", "/PieceInfo"):
        if key in pdf.Root:
            del pdf.Root[key]
            removed.append("XMP metadata" if key == "/Metadata" else "application data")
    for page in pdf.pages:
        for key in ("/Metadata", "/PieceInfo"):
            if key in page.obj:
                del page.obj[key]
    return removed


async def run(ctx: ToolContext) -> None:
    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            removed = clean(pdf)
            save_pdf(pdf, dst, deterministic_id=True)  # the /ID no longer reveals when it was saved
        return "removed " + ("; ".join(removed) if removed else "nothing (there was no metadata)") + "."

    await per_pdf(ctx, "Cleaning", "no metadata", ".pdf", work)
