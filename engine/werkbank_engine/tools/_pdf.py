"""Shared helpers for the PDF tools (pikepdf for structure, pypdfium2 for text and rendering,
reportlab for drawn text). Everything here is blocking: tools call it through ctx.in_thread."""

from __future__ import annotations

import contextlib
import io
import re
import threading
import zipfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

from werkbank_engine.files import output_name, safe_filename
from werkbank_engine.jobs import Reporter, ToolContext, ToolError

MM = 72 / 25.4  # points per millimetre
PAPER = {  # portrait width, height in points
    "a4": (210 * MM, 297 * MM),
    "a3": (297 * MM, 420 * MM),
    "letter": (612.0, 792.0),
}
_RANGE = re.compile(r"^(\d+)?\s*-\s*(\d+)?$")


class PageSpecError(ToolError):
    pass


def parse_pages(spec: str, count: int, *, empty_means_all: bool = True) -> list[int]:
    """ "1-3, 5, 8-" → zero-based page indexes, in the order given. Ranges may run backwards
    ("10-5"); "8-" runs to the last page and "-3" from the first."""
    spec = spec.strip()
    if not spec or spec.lower() == "all":
        if empty_means_all:
            return list(range(count))
        raise PageSpecError("Enter the pages, for example 1-3, 5.")
    result: list[int] = []
    for part in re.split(r"[,;]", spec):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            first = last = int(part)
        else:
            match = _RANGE.match(part)
            if not match or not (match.group(1) or match.group(2)):
                raise PageSpecError(f"'{part}' is not a page or a range such as 3-7.")
            first = int(match.group(1) or 1)
            last = int(match.group(2) or count)
        for n in (first, last):
            if not 1 <= n <= count:
                raise PageSpecError(
                    f"There is no page {n}: this PDF has {count} page{'s' if count != 1 else ''}."
                )
        step = 1 if last >= first else -1
        result.extend(i - 1 for i in range(first, last + step, step))
    if not result:
        raise PageSpecError("Enter the pages, for example 1-3, 5.")
    return result


def unique_pages(pages: list[int]) -> list[int]:
    seen: set[int] = set()
    for i in pages:
        if i in seen:
            raise PageSpecError(f"Page {i + 1} is listed more than once.")
        seen.add(i)
    return pages


def open_pdf(path: Path, name: str) -> pikepdf.Pdf:
    """Open a PDF with messages a user can act on. Password-protected PDFs must be unlocked first."""
    try:
        pdf = pikepdf.open(path)
    except pikepdf.PasswordError:
        raise ToolError(f"{name} needs a password to open. Use Unlock PDF first.") from None
    except pikepdf.PdfError as exc:
        raise ToolError(f"{name} is not a readable PDF ({exc}). Try Repair PDF.") from None
    if pdf.is_encrypted:
        # Owner-password PDFs open, but saving keeps restrictions ambiguous; be explicit instead.
        pdf.close()
        raise ToolError(f"{name} has restrictions (an owner password). Use Unlock PDF first.")
    return pdf


# PDFium is not thread-safe, and up to three light jobs run at once: one document at a time.
PDFIUM_LOCK = threading.Lock()


@contextlib.contextmanager
def pdfium_document(src: Path, name: str) -> Iterator[pdfium.PdfDocument]:
    with PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(src)
        except pdfium.PdfiumError as exc:
            if "password" in str(exc).lower():
                raise ToolError(f"{name} needs a password to open. Use Unlock PDF first.") from None
            raise ToolError(f"{name} is not a readable PDF ({exc}). Try Repair PDF.") from None
        try:
            yield doc
        finally:
            doc.close()


def save_pdf(pdf: pikepdf.Pdf, dst: Path, **kwargs: object) -> None:
    pdf.save(dst, object_stream_mode=pikepdf.ObjectStreamMode.generate, **kwargs)  # type: ignore[arg-type]


def zip_outputs(files: Iterable[tuple[Path, str]], dst: Path) -> int:
    """Pack `(path, name)` pairs into `dst`; names are made unique inside the archive."""
    used: set[str] = set()
    count = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, name in files:
            name = safe_filename(name)
            stem, dot, ext = name.rpartition(".")
            candidate, n = name, 2
            while candidate.lower() in used:
                candidate = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})"
                n += 1
            used.add(candidate.lower())
            zf.write(path, candidate)
            count += 1
    return count


def display_size(page: pikepdf.Page) -> tuple[float, float]:
    """Width and height of the visible page as a reader shows it (crop box, after /Rotate)."""
    box = page.cropbox
    w, h = float(box[2]) - float(box[0]), float(box[3]) - float(box[1])
    return (h, w) if page.rotation % 180 else (w, h)


def stamp_pages(
    pdf: pikepdf.Pdf,
    pages: list[int],
    draw: Callable[[object, float, float, int], None],
    report: Reporter | None = None,
) -> None:
    """Draw on pages with reportlab, upright as the reader sees them.

    `draw(canvas, width, height, page_index)` draws in display coordinates. Rotated pages are
    first flattened (/Rotate applied to their content), so the overlay needs no rotation maths."""
    from reportlab.pdfgen.canvas import Canvas

    buffer = io.BytesIO()
    canvas = Canvas(buffer)
    geometry: list[tuple[float, float, float, float]] = []  # crop box of each target page
    for n, index in enumerate(pages):
        page = pdf.pages[index]
        if page.rotation % 360:
            page.flatten_rotation()
        box = [float(v) for v in page.cropbox]
        width, height = box[2] - box[0], box[3] - box[1]
        canvas.setPageSize((width, height))
        draw(canvas, width, height, index)
        canvas.showPage()
        geometry.append((box[0], box[1], box[2], box[3]))
        if report and n % 20 == 0:
            report(0.5 * n / len(pages), None)
    canvas.save()
    overlay = pikepdf.open(io.BytesIO(buffer.getvalue()))
    for n, index in enumerate(pages):
        form = pdf.copy_foreign(overlay.pages[n].as_form_xobject())
        pdf.pages[index].add_overlay(form, pikepdf.Rectangle(*geometry[n]))
        if report and n % 20 == 0:
            report(0.5 + 0.5 * n / len(pages), None)


def pdf_inputs(ctx: ToolContext) -> list[tuple[int, str, Path]]:
    result = []
    for i, item in enumerate(ctx.inputs):
        if item.path is None:  # pragma: no cover - PDF tools only accept files
            raise ToolError("expected a file")
        result.append((i, item.name, item.path))
    return result


PerPdf = Callable[[Reporter, Path, Path, str], "str | None"]


async def per_pdf(ctx: ToolContext, verb: str, label: str, extension: str, fn: PerPdf) -> None:
    """Run `fn(report, src, dst, name)` in a thread for each input PDF. `dst` becomes the output
    `<name> (<label>)<extension>` if `fn` created it; the returned text becomes a note."""
    items = pdf_inputs(ctx)
    count = len(items)
    for i, name, src in items:
        dst = ctx.work / f"{i}{extension}"

        def work(
            report: Reporter, i: int = i, src: Path = src, dst: Path = dst, name: str = name
        ) -> str | None:
            def sub(fraction: float | None, message: str | None = None) -> None:
                report((i + min(max(fraction or 0.0, 0.0), 1.0)) / count, message)

            return fn(sub, src, dst, name)

        ctx.progress(i / count, f"{verb} {name}" + (f" ({i + 1} of {count})" if count > 1 else ""))
        note = await ctx.in_thread(work)
        if dst.is_file():
            ctx.add_output(dst, output_name(name, label, extension))
        if note:
            ctx.note(f"{name}: {note}")
