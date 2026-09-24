"""pdf.info — a plain-text report of what is inside a PDF."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pikepdf

from werkbank_engine.jobs import Reporter, ToolContext, ToolError
from werkbank_engine.tools._pdf import MM, PAPER, pdfium_document, per_pdf

HEAVY = False


def paper_name(width: float, height: float) -> str:
    short, long = sorted((width, height))
    for name, (w, h) in PAPER.items():
        if abs(short - w) < 3 and abs(long - h) < 3:
            label = "US Letter" if name == "letter" else name.upper()
            return f"{label} {'landscape' if width > height else 'portrait'}"
    return f"{width / MM:.0f} x {height / MM:.0f} mm"


def fonts(pdf: pikepdf.Pdf) -> tuple[set[str], set[str]]:
    embedded, missing = set(), set()
    for page in pdf.pages:
        for font in page.resources.get("/Font", {}).values():
            name = str(font.get("/BaseFont", "unnamed")).lstrip("/").split("+")[-1]
            descriptors = [font.get("/FontDescriptor")]
            for descendant in font.get("/DescendantFonts", []):
                descriptors.append(descendant.get("/FontDescriptor"))
            has_file = any(
                d is not None and any(k in d for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                for d in descriptors
            )
            (embedded if has_file else missing).add(name)
    return embedded, missing


def report_text(src: Path, name: str) -> str:
    lines = [f"PDF information: {name}", "=" * 60, f"File size: {src.stat().st_size / 1_048_576:.2f} MB"]
    try:
        pdf = pikepdf.open(src)
    except pikepdf.PasswordError:
        return "\n".join(
            [*lines, "Security: needs an open password; nothing else can be read without it.", ""]
        )
    except pikepdf.PdfError as exc:
        raise ToolError(f"{name} is not a readable PDF ({exc}). Try Repair PDF.") from None
    with pdf:
        lines.append(f"PDF version: {pdf.pdf_version}")
        lines.append(f"Pages: {len(pdf.pages)}")
        sizes = Counter(
            paper_name(float(p.mediabox[2] - p.mediabox[0]), float(p.mediabox[3] - p.mediabox[1]))
            for p in pdf.pages
        )
        lines.append("Page sizes: " + "; ".join(f"{size} ({n})" for size, n in sizes.most_common()))
        if pdf.is_encrypted:
            allowed = pdf.allow

            def state(flag: bool) -> str:
                return "allowed" if flag else "blocked"

            lines.append(
                f"Security: restricted (owner password); printing {state(allowed.print_highres)}, "
                f"copying {state(allowed.extract)}, editing {state(allowed.modify_other)}"
            )
        else:
            lines.append("Security: none")
        info = {k.lstrip("/"): str(v) for k, v in (pdf.trailer.get("/Info") or {}).items()}
        for key in (
            "Title",
            "Author",
            "Subject",
            "Keywords",
            "Creator",
            "Producer",
            "CreationDate",
            "ModDate",
        ):
            if info.get(key):
                lines.append(f"{key}: {info[key]}")
        xmp = pdf.open_metadata()
        part = xmp.get("pdfaid:part")
        if part:
            lines.append(f"Claims PDF/A-{part}{xmp.get('pdfaid:conformance', '').lower()} (not validated)")
        embedded, missing = fonts(pdf)
        lines.append(f"Fonts embedded: {', '.join(sorted(embedded)) or 'none'}")
        if missing:
            lines.append(f"Fonts NOT embedded (may look different elsewhere): {', '.join(sorted(missing))}")
        images = {img.objgen for page in pdf.pages for img in page.get_images().values()}
        lines.append(f"Images: {len(images)}")
        annots = Counter(
            str(a.get("/Subtype", "?")).lstrip("/") for p in pdf.pages for a in p.obj.get("/Annots", [])
        )
        widgets = annots.pop("Widget", 0)
        links = annots.pop("Link", 0)
        lines.append(f"Links: {links}")
        lines.append(
            f"Comments and annotations: {sum(annots.values())}" + (f" ({dict(annots)})" if annots else "")
        )
        form = pdf.Root.get("/AcroForm")
        fields = len(form.get("/Fields", [])) if form is not None else 0
        signatures = sum(
            1 for f in (form.get("/Fields", []) if form is not None else []) if f.get("/FT") == "/Sig"
        )
        lines.append(f"Form fields: {fields} (widgets: {widgets})")
        lines.append(f"Digital signature fields: {signatures}")
        attachments = list(pdf.attachments.keys())
        lines.append(
            f"Attachments: {len(attachments)}" + (f" ({', '.join(attachments)})" if attachments else "")
        )
        with pdf.open_outline() as outline:
            lines.append(f"Bookmarks: {'yes' if outline.root else 'none'}")
        lines.append(f"Fast web view (linearised): {'yes' if pdf.is_linearized else 'no'}")
    try:
        with pdfium_document(src, name) as doc:
            without_text = 0
            for page in doc:
                textpage = page.get_textpage()
                if len(textpage.get_text_bounded().strip()) < 10:
                    without_text += 1
                textpage.close()
        lines.append(
            "Text: every page has text"
            if not without_text
            else f"Text: {without_text} page(s) without text (scanned? OCR makes them searchable)"
        )
    except ToolError:
        pass
    return "\n".join(lines) + "\n"


async def run(ctx: ToolContext) -> None:
    def work(report: Reporter, src: Path, dst: Path, name: str) -> str:
        dst.write_text(report_text(src, name), encoding="utf-8")
        return "report saved."

    await per_pdf(ctx, "Inspecting", "info", ".txt", work)
