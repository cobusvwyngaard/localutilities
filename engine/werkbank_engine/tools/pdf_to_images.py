"""pdf.to-images — render pages with PDFium as PNG or JPG; several pages come in a ZIP."""

from __future__ import annotations

from pathlib import Path

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import parse_pages, pdf_inputs, pdfium_document, zip_outputs

HEAVY = True
MAX_PIXELS = 12_000 * 12_000  # a poster at 600 dpi would need gigabytes of memory


def render(report: Reporter, src: Path, name: str, work: Path, fmt: str, dpi: int, spec: str) -> list[Path]:
    with pdfium_document(src, name) as doc:
        pages = parse_pages(spec, len(doc))
        files = []
        for n, index in enumerate(pages):
            report(n / len(pages), f"Page {index + 1}")
            page = doc[index]
            width, height = page.get_size()
            scale = dpi / 72
            if width * height * scale * scale > MAX_PIXELS:
                scale = (MAX_PIXELS / (width * height)) ** 0.5
            image = page.render(scale=scale, may_draw_forms=True).to_pil()
            path = work / f"{Path(name).stem} p{index + 1}.{fmt}"
            if fmt == "jpg":
                image.convert("RGB").save(path, "JPEG", quality=90, dpi=(dpi, dpi))
            else:
                image.save(path, "PNG", dpi=(dpi, dpi), optimize=False)
            files.append(path)
        return files


async def run(ctx: ToolContext) -> None:
    fmt, dpi, spec = ctx.params["format"], ctx.params["dpi"], ctx.params["pages"]
    items = pdf_inputs(ctx)
    for i, name, src in items:
        folder = ctx.work / str(i)
        folder.mkdir()
        ctx.progress(i / len(items), f"Rendering {name}")
        files = await ctx.in_thread(render, src, name, folder, fmt, dpi, spec)
        if len(files) == 1:
            ctx.add_output(files[0], files[0].name)
        else:
            archive = ctx.work / f"{i}.zip"
            zip_outputs(((f, f.name) for f in files), archive)
            ctx.add_output(archive, f"{Path(name).stem} ({fmt.upper()} images).zip")
        ctx.note(f"{name}: {len(files)} page(s) as {fmt.upper()} at {dpi} dpi.")
