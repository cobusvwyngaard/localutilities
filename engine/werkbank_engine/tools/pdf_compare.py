"""pdf.compare — a side-by-side HTML report of the text differences between two PDFs."""

from __future__ import annotations

import difflib
from pathlib import Path

from werkbank_engine.files import output_name
from werkbank_engine.jobs import Reporter, ToolContext
from werkbank_engine.tools._pdf import pdf_inputs
from werkbank_engine.tools.pdf_to_text import extract_text

HEAVY = False


def text_lines(report: Reporter, src: Path, name: str) -> list[str]:
    lines: list[str] = []
    for index, text in extract_text(report, src, name, ""):
        lines.append(f"── Page {index + 1} ──")
        lines += [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines


def compare(report: Reporter, a: tuple[str, Path], b: tuple[str, Path], dst: Path) -> tuple[int, int]:
    left = text_lines(lambda f, m=None: report(0.4 * (f or 0), m), a[1], a[0])
    right = text_lines(lambda f, m=None: report(0.4 + 0.4 * (f or 0), m), b[1], b[0])
    report(0.85, "Comparing")
    html = difflib.HtmlDiff(wrapcolumn=80).make_file(left, right, a[0], b[0], context=True, numlines=2)
    html = html.replace("<head>", '<head>\n<meta name="viewport" content="width=device-width">', 1)
    dst.write_text(html, encoding="utf-8")
    changes = sum(1 for line in difflib.ndiff(left, right) if line[:1] in "+-")
    return changes, max(len(left), len(right))


async def run(ctx: ToolContext) -> None:
    (_, name_a, src_a), (_, name_b, src_b) = pdf_inputs(ctx)
    dst = ctx.work / "comparison.html"
    changes, _ = await ctx.in_thread(compare, (name_a, src_a), (name_b, src_b), dst)
    ctx.add_output(dst, output_name(name_a, "comparison", ".html"))
    if changes:
        ctx.note(f"{changes} changed line(s). Open the HTML file in your browser to see them side by side.")
    else:
        ctx.note("The text of the two PDFs is identical (layout and images were not compared).")
