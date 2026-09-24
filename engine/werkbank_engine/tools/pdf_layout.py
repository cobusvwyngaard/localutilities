"""pdf.layout — 1 page per sheet (resize), 2 or 4 per sheet, or a saddle-stitched booklet.

Each source page becomes a Form XObject (vector, lossless) scaled to fit its cell; qpdf keeps it
upright even when the source page has /Rotate."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import MM, PAPER, display_size, open_pdf, per_pdf, save_pdf

HEAVY = False
GAP = 5 * MM
Cell = tuple[float, float, float, float]


def booklet_order(count: int) -> list[int | None]:
    """Page order for 2-up double-sided printing, folded in the middle (None = blank)."""
    total = -(-count // 4) * 4
    pages: list[int | None] = [i if i < count else None for i in range(total)]
    order: list[int | None] = []
    for sheet in range(total // 4):
        order += [pages[total - 1 - 2 * sheet], pages[2 * sheet]]  # front: last, first
        order += [pages[2 * sheet + 1], pages[total - 2 - 2 * sheet]]  # back
    return order


def cells(layout: str, width: float, height: float) -> list[Cell]:
    if layout in ("2", "booklet"):
        half = width / 2
        return [(GAP, GAP, half - GAP / 2, height - GAP), (half + GAP / 2, GAP, width - GAP, height - GAP)]
    if layout == "4":
        mid_x, mid_y = width / 2, height / 2
        return [
            (GAP, mid_y + GAP / 2, mid_x - GAP / 2, height - GAP),
            (mid_x + GAP / 2, mid_y + GAP / 2, width - GAP, height - GAP),
            (GAP, GAP, mid_x - GAP / 2, mid_y - GAP / 2),
            (mid_x + GAP / 2, GAP, width - GAP, mid_y - GAP / 2),
        ]
    return [(0.0, 0.0, width, height)]


def sheet_size(layout: str, paper: str, source_landscape: bool) -> tuple[float, float]:
    w, h = PAPER[paper]
    landscape = source_landscape if layout in ("1", "4") else True
    return (h, w) if landscape else (w, h)


def impose(report: Reporter, src: Path, dst: Path, name: str, layout: str, paper: str) -> int:
    with open_pdf(src, name) as pdf, pikepdf.new() as out:
        count = len(pdf.pages)
        order: list[int | None] = booklet_order(count) if layout == "booklet" else list(range(count))
        per_sheet = {"1": 1, "2": 2, "4": 4, "booklet": 2}[layout]
        forms: dict[int, pikepdf.Object] = {}
        for start in range(0, len(order), per_sheet):
            report(start / len(order), f"Sheet {start // per_sheet + 1}")
            group = order[start : start + per_sheet]
            first = next((i for i in group if i is not None), 0)
            w, h = display_size(pdf.pages[first])
            sheet_w, sheet_h = sheet_size(layout, paper, w > h)
            sheet = out.add_blank_page(page_size=(sheet_w, sheet_h))
            for index, cell in zip(group, cells(layout, sheet_w, sheet_h), strict=False):
                if index is None:
                    continue
                if index not in forms:
                    forms[index] = out.copy_foreign(pdf.pages[index].as_form_xobject())
                sheet.add_overlay(forms[index], pikepdf.Rectangle(*cell))
        save_pdf(out, dst)
        return len(out.pages)


async def run(ctx: ToolContext) -> None:
    layout, paper = ctx.params["layout"], ctx.params["paper"]
    paper_label = {"a4": "A4", "a3": "A3", "letter": "US Letter"}[paper]

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        sheets = impose(report, src, dst, name, layout, paper)
        if layout == "booklet":
            return (
                f"booklet of {sheets} {paper_label} sides. Print double-sided, flipping on the short edge, "
                "then fold in the middle."
            )
        return f"{sheets} {paper_label} page(s). No quality loss (pages are placed as vector graphics)."

    await per_pdf(
        ctx,
        "Laying out",
        {"1": "resized", "booklet": "booklet"}.get(layout, f"{layout} per sheet"),
        ".pdf",
        work,
    )
