"""pdf.from-images — one image per page with img2pdf, which embeds JPEGs without re-compressing
them. Images img2pdf cannot take as they are (transparency, unusual modes) are converted first."""

from __future__ import annotations

import io
from pathlib import Path

import img2pdf
from PIL import Image, ImageOps

from werkbank_engine.files import output_name
from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import MM, PAPER

HEAVY = False
MARGIN = 10 * MM


def image_bytes(path: Path, name: str) -> tuple[bytes, bool]:
    """(data, converted): the file itself when img2pdf accepts it, else a lossless PNG copy."""
    data = path.read_bytes()
    try:
        img2pdf.convert(data)
    except Exception:  # img2pdf raises various errors for inputs it cannot embed as they are  # noqa: S110
        pass
    else:
        return data, False
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")
                flat.paste(rgba, mask=rgba.getchannel("A"))
                image = flat
            elif image.mode not in ("RGB", "L", "CMYK"):
                image = image.convert("RGB")
            out = io.BytesIO()
            image.save(out, "PNG")
            return out.getvalue(), True
    except OSError as exc:
        raise ToolError(f"{name} is not an image that can be read ({exc}).") from None


def build(report: Reporter, items: list[tuple[str, Path]], dst: Path, page_size: str) -> int:
    images, converted = [], 0
    for n, (name, path) in enumerate(items):
        report(0.8 * n / len(items), f"Adding {name}")
        data, was_converted = image_bytes(path, name)
        images.append(data)
        converted += was_converted
    layout = None
    if page_size in PAPER:
        layout = img2pdf.get_layout_fun(
            pagesize=PAPER[page_size], border=(MARGIN, MARGIN), fit=img2pdf.FitMode.into, auto_orient=True
        )
    report(0.9, "Saving")
    dst.write_bytes(img2pdf.convert(images, layout_fun=layout, rotation=img2pdf.Rotation.ifvalid))
    return converted


async def run(ctx: ToolContext) -> None:
    items = []
    for item in ctx.inputs:
        if item.path is None:  # pragma: no cover
            raise ToolError("expected a file")
        items.append((item.name, item.path))
    dst = ctx.work / "images.pdf"
    converted = await ctx.in_thread(build, items, dst, ctx.params["pageSize"])
    ctx.add_output(dst, output_name(items[0][0], "images", ".pdf"))
    kept = len(items) - converted
    note = f"{len(items)} image(s) on {len(items)} page(s)."
    if kept:
        note += f" {kept} embedded without re-compression (no quality loss)."
    if converted:
        note += f" {converted} converted losslessly first (transparency is placed on white)."
    ctx.note(note)
