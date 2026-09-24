"""pdf.flatten — form fields, comments and stamps become part of the page content."""

from __future__ import annotations

from pathlib import Path

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import open_pdf, per_pdf, save_pdf

HEAVY = False


async def run(ctx: ToolContext) -> None:
    def flatten(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            annotations = sum(len(page.obj.get("/Annots", [])) for page in pdf.pages)
            if "/AcroForm" in pdf.Root:
                pdf.generate_appearance_streams()  # filled-in values need an appearance to be drawn
            pdf.flatten_annotations(mode="print")  # what a printout would show
            if "/AcroForm" in pdf.Root:
                del pdf.Root["/AcroForm"]
            save_pdf(pdf, dst)
        if not annotations:
            return "had no form fields or annotations; saved a copy."
        return f"flattened {annotations} form field(s) and annotation(s)."

    await per_pdf(ctx, "Flattening", "flattened", ".pdf", flatten)
