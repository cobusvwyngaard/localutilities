"""pdf.protect — AES-256 encryption with an open password and optional restrictions.

The owner (permissions) password is random: if it equalled the open password, PDF readers
would grant full rights to anyone who opens the file and ignore the restrictions."""

from __future__ import annotations

import secrets
from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import open_pdf, per_pdf, save_pdf

HEAVY = False
MIN_PASSWORD = 4


def permissions(allow_print: bool, allow_copy: bool, allow_edit: bool) -> pikepdf.Permissions:
    return pikepdf.Permissions(
        accessibility=True,  # screen readers may always extract text
        extract=allow_copy,
        modify_annotation=allow_edit,
        modify_assembly=allow_edit,
        modify_form=allow_edit,
        modify_other=allow_edit,
        print_lowres=allow_print,
        print_highres=allow_print,
    )


async def run(ctx: ToolContext) -> None:
    password: str = ctx.params["password"]
    if len(password) < MIN_PASSWORD:
        raise ToolError(f"Enter a password of at least {MIN_PASSWORD} characters.")
    allow = permissions(ctx.params["allowPrint"], ctx.params["allowCopy"], ctx.params["allowEdit"])

    def protect(report: Reporter, src: Path, dst: Path, name: str) -> str:
        with open_pdf(src, name) as pdf:
            encryption = pikepdf.Encryption(user=password, owner=secrets.token_urlsafe(32), R=6, allow=allow)
            save_pdf(pdf, dst, encryption=encryption)
        return "encrypted with AES-256. Keep the password safe: it cannot be recovered."

    await per_pdf(ctx, "Protecting", "protected", ".pdf", protect)
