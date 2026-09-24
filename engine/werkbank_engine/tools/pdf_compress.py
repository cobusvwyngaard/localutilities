"""pdf.compress — lossless: object streams and re-compressed streams (qpdf). Balanced/strong also
shrink large photos and re-save them as JPEG. Never returns a bigger file than the original."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pikepdf
from PIL import Image

from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._ffmpeg import describe_size_change
from werkbank_engine.tools._pdf import open_pdf, per_pdf

HEAVY = True

LEVELS = {"balanced": (2000, 80), "strong": (1200, 65)}  # longest side in px, JPEG quality
MIN_PIXELS = 200 * 200  # icons and logos are left alone
SIMPLE_SPACES = {"/DeviceRGB": ("RGB", 3), "/DeviceGray": ("L", 1)}


def _colour_space(image: pikepdf.Stream) -> tuple[str, pikepdf.Object] | None:
    """Pillow mode and the /ColorSpace to write, for colour spaces that survive re-encoding."""
    cs = image.get("/ColorSpace")
    if isinstance(cs, pikepdf.Name) and str(cs) in SIMPLE_SPACES:
        return SIMPLE_SPACES[str(cs)][0], cs
    if isinstance(cs, pikepdf.Array) and len(cs) == 2 and cs[0] == pikepdf.Name.ICCBased:
        n = int(cs[1].get("/N", 0))
        if n in (1, 3):
            return ("L" if n == 1 else "RGB"), cs
    return None


def recompress_image(image: pikepdf.Stream, max_side: int, quality: int) -> int:
    """Re-encode one image XObject in place; returns bytes saved (0 if left alone)."""
    if image.get("/ImageMask") or "/Decode" in image or image.get("/BitsPerComponent") != 8:
        return 0
    filters = image.get("/Filter")
    names = [
        str(f) for f in (filters if isinstance(filters, pikepdf.Array) else [filters] if filters else [])
    ]
    if any(f not in ("/DCTDecode", "/FlateDecode", "/ASCII85Decode", "/ASCIIHexDecode") for f in names):
        return 0  # JPEG 2000, JBIG2, CCITT, LZW: leave as they are
    space = _colour_space(image)
    if space is None:
        return 0
    mode, cs = space
    width, height = int(image.Width), int(image.Height)
    if width * height < MIN_PIXELS:
        return 0
    try:
        pil = pikepdf.PdfImage(image).as_pil_image().convert(mode)
    except Exception:
        return 0
    scale = min(1.0, max_side / max(width, height))
    if scale < 1.0:
        pil = pil.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS
        )
    out = io.BytesIO()
    pil.save(out, "JPEG", quality=quality, optimize=True)
    data = out.getvalue()
    before = len(image.read_raw_bytes())
    if len(data) >= before:
        return 0
    image.write(data, filter=pikepdf.Name.DCTDecode)
    image.Width, image.Height = pil.width, pil.height
    image.ColorSpace = cs
    image.BitsPerComponent = 8
    if "/DecodeParms" in image:
        del image["/DecodeParms"]
    return before - len(data)


def compress(report: Reporter, src: Path, dst: Path, level: str) -> tuple[int, int]:
    """Returns (images re-compressed, bytes saved on images)."""
    changed = saved = 0
    with open_pdf(src, src.name) as pdf:
        if level in LEVELS:
            max_side, quality = LEVELS[level]
            seen: set[tuple[int, int]] = set()
            for n, page in enumerate(pdf.pages):
                report(0.8 * n / len(pdf.pages), f"Page {n + 1} of {len(pdf.pages)}")
                for image in page.get_images().values():
                    if image.objgen in seen:
                        continue
                    seen.add(image.objgen)
                    gain = recompress_image(image, max_side, quality)
                    changed += gain > 0
                    saved += gain
        report(0.85, "Saving")
        pdf.remove_unreferenced_resources()
        pdf.save(
            dst,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            compress_streams=True,
            recompress_flate=True,
        )
    return changed, saved


async def run(ctx: ToolContext) -> None:
    level = ctx.params["level"]

    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        changed, _ = compress(report, src, dst, level)
        before, after = src.stat().st_size, dst.stat().st_size
        if after >= before:
            shutil.copyfile(src, dst)
            return "already compact: this level could not make it smaller, so it is unchanged."
        images = f"; {changed} image(s) re-compressed" if changed else ""
        lossless = " No quality loss." if level == "lossless" or not changed else ""
        return f"{describe_size_change(before, after)}{images}.{lossless}"

    await per_pdf(ctx, "Compressing", "compressed", ".pdf", work)
