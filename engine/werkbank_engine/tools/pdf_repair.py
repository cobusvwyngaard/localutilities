"""pdf.repair — let qpdf rebuild the file; fall back to PDFium, which accepts more damage."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import pdfium_document, per_pdf, save_pdf

HEAVY = False


def repair(src: Path, dst: Path) -> str:
    try:
        with pikepdf.open(src) as pdf:
            warnings = pdf.get_warnings()
            if pdf.is_encrypted:
                raise ToolError("This PDF is protected. Use Unlock PDF first.")
            save_pdf(pdf, dst)
        if warnings:
            return f"repaired ({len(warnings)} problem(s) fixed, e.g. {warnings[0]})."
        return "no damage found; saved a cleanly rebuilt copy."
    except pikepdf.PasswordError:
        raise ToolError("This PDF needs a password to open. Use Unlock PDF first.") from None
    except pikepdf.PdfError as first:
        try:
            with pdfium_document(src, src.name) as doc, dst.open("wb") as fh:
                pages = len(doc)
                doc.save(fh)
        except ToolError:
            raise ToolError(f"Could not repair this PDF: {first}") from None
        return f"repaired with the second method (PDFium); {pages} page(s) recovered. Check every page."


async def run(ctx: ToolContext) -> None:
    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        return repair(src, dst)

    await per_pdf(ctx, "Repairing", "repaired", ".pdf", work)
