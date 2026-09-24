"""pdf.extract — embedded images in their stored format, or attached files, in a ZIP."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from werkbank_engine.files import safe_filename
from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import open_pdf, per_pdf, zip_outputs

HEAVY = False


def extract_images(
    report: Reporter, pdf: pikepdf.Pdf, folder: Path, stem: str
) -> tuple[list[tuple[Path, str]], int]:
    files, skipped, seen = [], 0, set()
    for n, page in enumerate(pdf.pages):
        report(n / len(pdf.pages), f"Page {n + 1}")
        for key, image in page.get_images().items():
            if image.objgen in seen:
                continue
            seen.add(image.objgen)
            try:
                written = pikepdf.PdfImage(image).extract_to(fileprefix=str(folder / f"{len(files)}"))
            except Exception:
                skipped += 1
                continue
            path = Path(written)
            files.append((path, f"{stem} p{n + 1} {str(key).lstrip('/')}{path.suffix}"))
    return files, skipped


def extract_attachments(pdf: pikepdf.Pdf, folder: Path) -> list[tuple[Path, str]]:
    files = []
    for n, (name, spec) in enumerate(pdf.attachments.items()):
        path = folder / f"a{n}"
        path.write_bytes(spec.get_file().read_bytes())
        files.append((path, safe_filename(spec.filename or name)))
    return files


async def run(ctx: ToolContext) -> None:
    what = ctx.params["what"]

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        folder = dst.with_suffix("")
        folder.mkdir()
        with open_pdf(src, name) as pdf:
            if what == "images":
                files, skipped = extract_images(report, pdf, folder, Path(name).stem)
            else:
                files, skipped = extract_attachments(pdf, folder), 0
        if not files:
            return "no images found." if what == "images" else "no attached files found."
        zip_outputs(files, dst)
        extra = f" {skipped} could not be extracted." if skipped else ""
        kind = "image(s) in their original format" if what == "images" else "attached file(s)"
        return f"extracted {len(files)} {kind}.{extra}"

    await per_pdf(ctx, "Extracting from", what, ".zip", work)
