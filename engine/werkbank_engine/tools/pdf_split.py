"""pdf.split — single pages, parts of N pages, or one PDF per page range; delivered as a ZIP."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import PageSpecError, open_pdf, parse_pages, per_pdf, save_pdf, zip_outputs

HEAVY = False


def groups(mode: str, count: int, chunk: int, ranges: str) -> list[list[int]]:
    if mode == "pages":
        return [[i] for i in range(count)]
    if mode == "chunks":
        return [list(range(start, min(start + chunk, count))) for start in range(0, count, chunk)]
    parts = [p for p in ranges.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise PageSpecError("Enter the page ranges, for example 1-3, 4-10, 11-.")
    return [parse_pages(p, count, empty_means_all=False) for p in parts]


def label(pages: list[int]) -> str:
    first, last = pages[0] + 1, pages[-1] + 1
    return f"p{first}" if first == last else f"p{first}-{last}"


async def run(ctx: ToolContext) -> None:
    mode, chunk, ranges = ctx.params["mode"], ctx.params["chunk"], ctx.params["ranges"]

    def split(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            parts = groups(mode, len(pdf.pages), chunk, ranges)
            if mode != "ranges" and len(parts) == 1:
                raise ToolError(f"{name} has only {len(pdf.pages)} page(s): nothing to split.")
            files = []
            for n, pages in enumerate(parts):
                report(n / len(parts) * 0.9, f"Part {n + 1} of {len(parts)}")
                part_path = dst.with_name(f"{dst.stem}-{n}.pdf")
                with pikepdf.new() as part:
                    part.pages.extend(pdf.pages[i] for i in pages)
                    save_pdf(part, part_path)
                files.append((part_path, f"{Path(name).stem} {label(pages)}.pdf"))
        zip_outputs(files, dst)
        return f"split into {len(parts)} PDFs (in one ZIP file)."

    await per_pdf(ctx, "Splitting", "split", ".zip", split)
