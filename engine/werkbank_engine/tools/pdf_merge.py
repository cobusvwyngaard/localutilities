"""pdf.merge — combine PDFs in the order they were added, with a bookmark per file."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pikepdf

from werkbank_engine.files import output_name
from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import open_pdf, pdf_inputs, save_pdf

HEAVY = False


def merge(report: Reporter, items: list[tuple[int, str, Path]], dst: Path, bookmarks: bool) -> int:
    with contextlib.ExitStack() as stack:
        out = stack.enter_context(pikepdf.new())
        marks: list[tuple[str, int]] = []
        for n, (_, name, src) in enumerate(items):
            report(n / len(items) * 0.8, f"Adding {name}")
            pdf = stack.enter_context(open_pdf(src, name))  # sources must stay open until saved
            marks.append((Path(name).stem, len(out.pages)))
            out.pages.extend(pdf.pages)
        if bookmarks:
            with out.open_outline() as outline:
                outline.root.extend(pikepdf.OutlineItem(title, page) for title, page in marks)
        report(0.85, "Saving")
        save_pdf(out, dst)
        return len(out.pages)


async def run(ctx: ToolContext) -> None:
    items = pdf_inputs(ctx)
    dst = ctx.work / "merged.pdf"
    pages = await ctx.in_thread(merge, items, dst, ctx.params["bookmarks"])
    ctx.add_output(dst, output_name(items[0][1], "merged", ".pdf"))
    ctx.note(f"Merged {len(items)} files into one PDF of {pages} pages.")
