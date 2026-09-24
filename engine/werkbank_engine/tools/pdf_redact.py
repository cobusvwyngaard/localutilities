"""pdf.redact — true redaction: pages with a match get black boxes and are then replaced by an
image of themselves, so the covered text is gone from the file (not just hidden). The result is
checked: if any search term can still be found, the job fails instead of giving a false sense of
safety."""

from __future__ import annotations

import io
import re
from pathlib import Path

import img2pdf
import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import open_pdf, pdfium_document, per_pdf, save_pdf

HEAVY = True
DPI = 200
PAD = 1.5  # points around each match
Rect = tuple[float, float, float, float]


def parse_terms(raw: str) -> list[str]:
    terms = [t.strip() for t in re.split(r"[;\n]", raw) if t.strip()]
    if not terms:
        raise ToolError("Enter the words or phrases to black out, separated by ;")
    short = [t for t in terms if len(t) < 2]
    if short:
        raise ToolError("Each word or phrase needs at least 2 characters.")
    return terms


def find(src: Path, name: str, terms: list[str], match_case: bool) -> dict[int, list[Rect]]:
    """Page index → rectangles (PDF user space) of every match."""
    hits: dict[int, list[Rect]] = {}
    with pdfium_document(src, name) as doc:
        for index, page in enumerate(doc):
            textpage = page.get_textpage()
            for term in terms:
                searcher = textpage.search(term, match_case=match_case)
                while (found := searcher.get_next()) is not None:
                    start, count = found
                    for k in range(textpage.count_rects(start, count)):
                        hits.setdefault(index, []).append(textpage.get_rect(k))
                searcher.close()
            textpage.close()
    return hits


def draw_boxes(pdf: pikepdf.Pdf, index: int, rects: list[Rect]) -> None:
    page = pdf.pages[index]
    ops = "".join(
        f"{left - PAD:.2f} {bottom - PAD:.2f} {right - left + 2 * PAD:.2f} {top - bottom + 2 * PAD:.2f} re\n"
        for left, bottom, right, top in rects
    )
    page.contents_add(pikepdf.Stream(pdf, b"q\n"), prepend=True)
    page.contents_add(pikepdf.Stream(pdf, f"\nQ\nq 0 g\n{ops}f\nQ\n".encode()))


def rasterise(src: Path, name: str, pages: list[int]) -> dict[int, bytes]:
    """Page index → a one-page PDF holding only the rendered image of that page."""
    result = {}
    with pdfium_document(src, name) as doc:
        for index in pages:
            page = doc[index]
            width, height = page.get_size()
            image = page.render(scale=DPI / 72, may_draw_forms=True).to_pil().convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            layout = img2pdf.get_layout_fun(pagesize=(width, height), fit=img2pdf.FitMode.exact)
            result[index] = img2pdf.convert(buffer.getvalue(), layout_fun=layout)
    return result


async def run(ctx: ToolContext) -> None:
    terms = parse_terms(ctx.params["terms"])
    match_case = ctx.params["caseSensitive"]

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str | None:
        report(0.05, "Searching")
        hits = find(src, name, terms, match_case)
        if not hits:
            return "none of the words or phrases were found; nothing was changed."
        boxed = dst.with_name(dst.stem + "-boxed.pdf")
        with open_pdf(src, name) as pdf:
            for index, rects in hits.items():
                draw_boxes(pdf, index, rects)
            save_pdf(pdf, boxed)
        report(0.4, "Replacing pages with images")
        images = rasterise(boxed, name, sorted(hits))
        with pikepdf.open(boxed) as pdf:
            for index, data in sorted(images.items()):
                with pikepdf.open(io.BytesIO(data)) as single:
                    pdf.pages.insert(index, single.pages[0])
                del pdf.pages[index + 1]
            save_pdf(pdf, dst)
        boxed.unlink()
        report(0.9, "Checking the result")
        if find(dst, name, terms, match_case):
            dst.unlink()
            raise ToolError(
                "Checking the result found text that should have been removed. Nothing was saved."
            )
        count = sum(len(r) for r in hits.values())
        pages = ", ".join(str(i + 1) for i in sorted(hits))
        return (
            f"blacked out {count} match(es) on page(s) {pages}. Those pages are now images. "
            "The document information (title, author) was not changed: use Remove PDF metadata if needed."
        )

    await per_pdf(ctx, "Redacting", "redacted", ".pdf", work)
