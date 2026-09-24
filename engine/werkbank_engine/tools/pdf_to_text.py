"""pdf.to-text — the text layer of each page, via PDFium, into one UTF-8 text file."""

from __future__ import annotations

from pathlib import Path

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import parse_pages, pdfium_document, per_pdf

HEAVY = False


def extract_text(report: Reporter, src: Path, name: str, spec: str) -> list[tuple[int, str]]:
    with pdfium_document(src, name) as doc:
        pages = parse_pages(spec, len(doc))
        result = []
        for n, index in enumerate(pages):
            if n % 10 == 0:
                report(n / len(pages), f"Page {index + 1}")
            textpage = doc[index].get_textpage()
            result.append((index, textpage.get_text_bounded().replace("\r\n", "\n").strip()))
            textpage.close()
        return result


async def run(ctx: ToolContext) -> None:
    spec = ctx.params["pages"]

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        pages = extract_text(report, src, name, spec)
        body = "\n\n".join(f"--- Page {index + 1} ---\n{text}" for index, text in pages)
        dst.write_text(body + "\n", encoding="utf-8")
        empty = sum(1 for _, text in pages if not text)
        words = sum(len(text.split()) for _, text in pages)
        note = f"{words} words from {len(pages)} page(s)."
        if empty:
            note += f" {empty} page(s) had no text (probably scanned: use OCR first)."
        return note

    await per_pdf(ctx, "Extracting text from", "text", ".txt", work)
