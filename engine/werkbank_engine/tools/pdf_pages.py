"""pdf.pages — keep pages in a chosen order, or delete pages."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import open_pdf, parse_pages, per_pdf, save_pdf, unique_pages

HEAVY = False


async def run(ctx: ToolContext) -> None:
    action, spec = ctx.params["action"], ctx.params["pages"]

    def edit(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            count = len(pdf.pages)
            chosen = unique_pages(parse_pages(spec, count, empty_means_all=False))
            if action == "delete":
                if len(chosen) == count:
                    raise ToolError("That would delete every page.")
                keep = [i for i in range(count) if i not in set(chosen)]
            else:
                keep = chosen
            with pikepdf.new() as out:
                out.pages.extend(pdf.pages[i] for i in keep)
                save_pdf(out, dst)
        if action == "delete":
            return f"deleted {len(chosen)} page(s); {len(keep)} left."
        return f"kept {len(keep)} of {count} pages in the order given."

    await per_pdf(ctx, "Editing pages of", "pages", ".pdf", edit)
