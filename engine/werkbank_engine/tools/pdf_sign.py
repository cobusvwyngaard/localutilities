"""pdf.sign — a PAdES digital signature with the user's own certificate (pyHanko).

Nothing is contacted online: no timestamp server and no revocation lookups, so the signature
shows the signing time from this computer's clock. The certificate password is used in-process
and never logged."""

from __future__ import annotations

from pathlib import Path

import pikepdf
from pyhanko import stamp
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers

from werkbank_engine.files import output_name
from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import MM

HEAVY = False
BOX = (70 * MM, 22 * MM)  # width, height of the visible signature
CERT_EXTENSIONS = {".p12", ".pfx"}


def split_inputs(ctx: ToolContext) -> tuple[tuple[str, Path], Path]:
    pdfs = [(i.name, i.path) for i in ctx.inputs if i.path and Path(i.name).suffix.lower() == ".pdf"]
    certs = [i.path for i in ctx.inputs if i.path and Path(i.name).suffix.lower() in CERT_EXTENSIONS]
    if len(pdfs) != 1 or len(certs) != 1:
        raise ToolError("Add exactly one PDF and one certificate file (.p12 or .pfx).")
    return pdfs[0], certs[0]


def load_signer(cert: Path, password: str) -> signers.SimpleSigner:
    try:
        signer = signers.SimpleSigner.load_pkcs12(cert, passphrase=password.encode() if password else None)
    except Exception:
        signer = None
    if signer is None:
        raise ToolError("The certificate could not be opened: check the certificate password and the file.")
    return signer


def field_name(src: Path) -> str:
    with pikepdf.open(src) as pdf:
        form = pdf.Root.get("/AcroForm")
        names = {str(f.get("/T", "")) for f in (form.get("/Fields", []) if form is not None else [])}
    n = 1
    while f"Signature{n}" in names:
        n += 1
    return f"Signature{n}"


def last_page_box(src: Path) -> tuple[int, int, tuple[int, int, int, int]]:
    with pikepdf.open(src) as pdf:
        index = len(pdf.pages) - 1
        x0, y0 = (float(v) for v in pdf.pages[index].cropbox[:2])
    left, bottom = x0 + 20 * MM, y0 + 20 * MM
    return index, len(pdf.pages), (round(left), round(bottom), round(left + BOX[0]), round(bottom + BOX[1]))


def sign(report: Reporter, src: Path, name: str, cert: Path, dst: Path, params: dict) -> str:
    signer = load_signer(cert, params["password"])
    try:
        name_field = field_name(src)
        index, _, box = last_page_box(src)
    except pikepdf.PasswordError:
        raise ToolError(f"{name} is password-protected. Unlock it first.") from None
    except pikepdf.PdfError as exc:
        raise ToolError(f"{name} is not a readable PDF ({exc}).") from None
    meta = signers.PdfSignatureMetadata(
        field_name=name_field,
        reason=params["reason"] or None,
        location=params["location"] or None,
        md_algorithm="sha256",
    )
    spec = fields.SigFieldSpec(name_field, on_page=index, box=box) if params["visible"] else None
    style = stamp.TextStampStyle(
        stamp_text="Digitally signed by %(signer)s\n%(ts)s", timestamp_format="%Y-%m-%d %H:%M %Z"
    )
    report(0.3, "Signing")
    with src.open("rb") as inf:
        try:
            writer = IncrementalPdfFileWriter(inf, strict=False)
        except Exception as exc:
            raise ToolError(f"{name} could not be prepared for signing ({exc}).") from None
        if writer.security_handler is not None:
            raise ToolError(f"{name} is encrypted. Unlock it first.")
        pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=style, new_field_spec=spec)
        with dst.open("wb") as out:
            pdf_signer.sign_pdf(writer, output=out)
    subject = signer.signing_cert.subject.human_friendly
    return f"signed as {subject}" + (" (visible box on the last page)" if params["visible"] else "") + "."


async def run(ctx: ToolContext) -> None:
    (name, src), cert = split_inputs(ctx)
    dst = ctx.work / "signed.pdf"
    ctx.progress(0.0, f"Signing {name}")
    note = await ctx.in_thread(sign, src, name, cert, dst, ctx.params)
    ctx.add_output(dst, output_name(name, "signed", ".pdf"))
    ctx.note(
        f"{name}: {note} Readers show the signature as valid only if they trust your certificate; "
        "the signing time comes from this computer's clock."
    )
