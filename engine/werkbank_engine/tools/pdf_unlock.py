"""pdf.unlock — DESIGN.md §5.4. No password cracking: a user (open) password must be supplied.

pikepdf runs in-process (not the qpdf CLI), so the password never appears in a process list,
and it is never logged or returned to the UI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import pikepdf

from werkbank_engine.files import output_name
from werkbank_engine.jobs import ToolContext, ToolError

HEAVY = False

Kind = Literal["none", "owner", "user"]


def unlock(src: Path, dst: Path, password: str) -> Kind:
    """Save an unencrypted copy of `src` to `dst`; returns which protection was found."""
    try:
        pdf = pikepdf.open(src)  # works for unprotected PDFs and owner-password-only PDFs
        kind: Kind = "owner" if pdf.is_encrypted else "none"
    except pikepdf.PasswordError:
        if not password:
            raise ToolError(
                "This PDF has an open (user) password. Enter it in the password field and try again."
            ) from None
        try:
            pdf = pikepdf.open(src, password=password)
        except pikepdf.PasswordError:
            raise ToolError("That password does not open this PDF.") from None
        kind = "user"
    except pikepdf.PdfError as exc:
        raise ToolError(f"Not a readable PDF: {exc}") from None
    with pdf:
        if kind != "none":
            pdf.save(dst)  # pikepdf saves without encryption unless asked to encrypt
    return kind


MESSAGES = {
    "owner": "Removed the permissions (owner) password. No password was needed.",
    "user": "Opened with your password and saved an unprotected copy.",
    "none": "Not password-protected; nothing to do.",
}


async def run(ctx: ToolContext) -> None:
    password: str = ctx.params["password"]
    count = len(ctx.inputs)
    for i, item in enumerate(ctx.inputs):
        src = item.path
        if src is None:  # pragma: no cover - this tool only accepts files
            raise ToolError("expected a file")
        ctx.progress(i / count, f"Unlocking {item.name}")
        dst = ctx.work / f"{i}.pdf"
        try:
            kind = await asyncio.to_thread(unlock, src, dst, password)
        except ToolError as exc:
            raise ToolError(f"{item.name}: {exc}") from None
        ctx.note(f"{item.name}: {MESSAGES[kind]}")
        if kind != "none":
            ctx.add_output(dst, output_name(item.name, "unlocked", ".pdf"))
