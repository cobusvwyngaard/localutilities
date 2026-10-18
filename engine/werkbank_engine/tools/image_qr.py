"""image.qr — a QR code for a web address, as PNG, SVG and/or PDF (segno, pure Python).

The code uses the standard four-module quiet zone, so it scans when printed on any background.
Nothing is contacted: the address is only encoded, never opened."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import segno

from werkbank_engine.files import safe_filename
from werkbank_engine.jobs import Reporter, ToolContext, ToolError

HEAVY = False
BORDER = 4  # modules of quiet zone required by ISO/IEC 18004
FORMATS = {"png": ("png",), "svg": ("svg",), "pdf": ("pdf",), "all": ("png", "svg", "pdf")}
ERROR_LEVELS = {"l": "7 %", "m": "15 %", "q": "25 %", "h": "30 %"}


def base_name(url: str) -> str:
    """ "QR example.com-docs-page" — readable, and safe on every file system."""
    parts = urlsplit(url)
    path = parts.path.strip("/").replace("/", "-")
    label = parts.netloc + (f"-{path}" if path else "")
    return safe_filename(f"QR {label}", fallback="QR code", max_length=80)


def make(url: str, error: str) -> segno.QRCode:
    try:
        # boost_error: use a stronger error level when it fits in the same size, for free.
        return segno.make_qr(url, error=error, boost_error=True)
    except segno.DataOverflowError:
        raise ToolError(
            "This address is too long for a QR code at this error correction level. "
            "Choose a lower level or use a shorter address."
        ) from None


def write(report: Reporter, url: str, folder: Path, params: dict) -> tuple[segno.QRCode, list[Path], int]:
    qr = make(url, params["errorCorrection"])
    modules = qr.symbol_size(scale=1, border=BORDER)[0]
    scale = max(1, round(params["size"] / modules))  # whole pixels per module keep the edges sharp
    paths = []
    for fmt in FORMATS[params["format"]]:
        path = folder / f"qr.{fmt}"
        if fmt == "png":
            qr.save(path, kind="png", scale=scale, border=BORDER)
        elif fmt == "svg":
            qr.save(path, kind="svg", scale=10, border=BORDER, xmldecl=False, svgclass=None, lineclass=None)
        else:
            qr.save(path, kind="pdf", scale=4, border=BORDER)  # 4 pt per module; vector, any size
        paths.append(path)
    return qr, paths, modules * scale


async def run(ctx: ToolContext) -> None:
    url = ctx.inputs[0].url
    if url is None:  # pragma: no cover - this tool only accepts a web address
        raise ToolError("expected a web address")
    ctx.progress(0.1, "Making the QR code")
    qr, paths, pixels = await ctx.in_thread(write, url, ctx.work, ctx.params)
    name = base_name(url)
    for path in paths:
        ctx.add_output(path, f"{name}{path.suffix}")
    formats = FORMATS[ctx.params["format"]]
    level = str(qr.error).lower()
    note = f"QR code version {qr.version} with {ERROR_LEVELS[level]} error correction ({level.upper()})."
    if "png" in formats:
        note += f" PNG: {pixels} x {pixels} px."
    if "svg" in formats or "pdf" in formats:
        note += " SVG and PDF are vector files that stay sharp at any size."
    ctx.note(note + " Scan it once before printing.")
