"""pdf.ocr — searchable PDFs with Tesseract, without Ghostscript or OCRmyPDF.

Each page without text is rendered by PDFium (as the reader sees it), Tesseract turns the image
into a text-only PDF page (`textonly_pdf=1`), and that invisible text layer is laid over the
original page. The page's own content is never changed, so nothing loses quality."""

from __future__ import annotations

import os
from pathlib import Path

import pikepdf

from werkbank_engine.files import output_name
from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import open_pdf, pdf_inputs, pdfium_document, save_pdf

HEAVY = True
MIN_TEXT = 20  # characters; pages with more are treated as already searchable


def tessdata_dir(tesseract: str) -> Path | None:
    """The portable app keeps tessdata next to tesseract.exe; elsewhere Tesseract knows its own."""
    folder = Path(tesseract).parent / "tessdata"
    return folder if folder.is_dir() else None


def pages_needing_ocr(report: Reporter, src: Path, name: str) -> tuple[int, list[int]]:
    with pdfium_document(src, name) as doc:
        todo = []
        for i, page in enumerate(doc):
            textpage = page.get_textpage()
            if len(textpage.get_text_bounded().strip()) < MIN_TEXT:
                todo.append(i)
            textpage.close()
        return len(doc), todo


def render_page(report: Reporter, src: Path, name: str, index: int, dpi: int, dst: Path) -> None:
    with pdfium_document(src, name) as doc:
        doc[index].render(scale=dpi / 72, grayscale=True, may_draw_forms=True).to_pil().save(
            dst, dpi=(dpi, dpi)
        )


def build_args(tesseract: str, image: Path, out_base: Path, language: str, dpi: int) -> list[str]:
    args = [tesseract, str(image), str(out_base), "-l", language, "--dpi", str(dpi)]
    folder = tessdata_dir(tesseract)
    if folder is not None:
        args += ["--tessdata-dir", str(folder)]
    return [*args, "-c", "textonly_pdf=1", "pdf"]


def add_text_layers(report: Reporter, src: Path, name: str, layers: dict[int, Path], dst: Path) -> None:
    with open_pdf(src, name) as pdf:
        for n, (index, layer_path) in enumerate(sorted(layers.items())):
            report(n / len(layers), None)
            page = pdf.pages[index]
            if page.rotation % 360:
                page.flatten_rotation()  # the text layer was made from the page as displayed
            with pikepdf.open(layer_path) as layer:
                form = pdf.copy_foreign(layer.pages[0].as_form_xobject())
            page.add_overlay(form, pikepdf.Rectangle(*(float(v) for v in page.cropbox)))
        save_pdf(pdf, dst)


async def run(ctx: ToolContext) -> None:
    tesseract = ctx.program("tesseract")
    language, dpi = ctx.params["language"], ctx.params["dpi"]
    env = dict(os.environ, OMP_THREAD_LIMIT="1")  # one page at a time; avoids oversubscribing cores
    items = pdf_inputs(ctx)
    for i, name, src in items:
        base, span = i / len(items), 1 / len(items)
        total, todo = await ctx.in_thread(pages_needing_ocr, src, name)
        if not todo:
            ctx.note(f"{name}: every page already has text; nothing to do.")
            continue
        folder = ctx.work / str(i)
        folder.mkdir()
        layers: dict[int, Path] = {}
        for n, index in enumerate(todo):
            ctx.progress(
                base + span * 0.95 * n / len(todo),
                f"Reading page {index + 1} of {name} ({n + 1} of {len(todo)})",
            )
            image = folder / f"{index}.png"
            await ctx.in_thread(render_page, src, name, index, dpi, image)
            out_base = folder / f"{index}"
            try:
                await ctx.run(
                    build_args(tesseract, image, out_base, language, dpi), env=env, what="Tesseract"
                )
            except ToolError as exc:
                if "Failed loading language" in str(exc) or "Error opening data file" in str(exc):
                    raise ToolError(f"The OCR language data for '{language}' is missing. {exc}") from None
                raise
            image.unlink()
            layers[index] = out_base.with_suffix(".pdf")
        dst = ctx.work / f"{i}.pdf"
        ctx.progress(base + span * 0.96, f"Saving {name}")
        await ctx.in_thread(add_text_layers, src, name, layers, dst)
        ctx.add_output(dst, output_name(name, "searchable", ".pdf"))
        skipped = total - len(todo)
        ctx.note(
            f"{name}: recognised text on {len(todo)} page(s)"
            + (f"; {skipped} page(s) already had text" if skipped else "")
            + ". The pages look exactly as before. Check important text: OCR can misread."
        )
