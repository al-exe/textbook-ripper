#!/usr/bin/env python3
"""Make iPad-friendly PDFs that mirror the Markdown study sheets.

    .venv/bin/python tools/pdf.py                 # every study/**/*.md
    .venv/bin/python tools/pdf.py "study/Chinese 3/grammar/unit-04-talking-about-housing.md"

Each PDF goes to pdf/ at the same relative path as its .md in study/. The PDF has the same content
as the Markdown, laid out for handwriting:
  * pinyin sits under the characters (as in the textbook);
  * a wide right margin for notes, ruled writing lines under every exercise prompt,
    a ruled "Notes" box after each grammar note;
  * the answer key is expanded and starts on a new page;
  * vocabulary tables get an extra blank column for practising the characters.
Requires Google Chrome (headless) for HTML -> PDF.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt

import paths

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HTML_DIR = paths.CACHE / "_html"

CSS = """
@page { size: A4; margin: 16mm 48mm 16mm 16mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "PingFang SC", "Hiragino Sans GB", "Helvetica Neue", Arial, sans-serif;
       font-size: 11.5pt; line-height: 1.55; color: #1d1d1f; }
h1 { font-size: 19pt; margin: 0 0 4mm; border-bottom: 2px solid #c0392b; padding-bottom: 2mm; }
h2 { font-size: 15pt; margin: 8mm 0 3mm; color: #c0392b; }
h3 { font-size: 13pt; margin: 6mm 0 2mm; color: #1f4e79; break-after: avoid; }
p { margin: 1.5mm 0 3mm; }
ruby { ruby-position: under; ruby-align: center; margin: 0 0.14em; line-height: 1.25; }
rt { font-size: 0.68em; color: #1f4e79; padding: 0 0.12em; letter-spacing: 0;
     font-family: "Helvetica Neue", Arial, sans-serif; }
p:has(ruby), li:has(ruby) { line-height: 1.9; }
blockquote { margin: 3mm 0; padding: 1mm 4mm; border-left: 3px solid #d5dbe5; background: #f6f8fb; }
ol, ul { padding-left: 7mm; }
li { margin-bottom: 2mm; }
table { border-collapse: collapse; width: 100%; font-size: 10.5pt; }
th, td { border: 1px solid #c8ccd2; padding: 1.6mm 2mm; vertical-align: top; }
th { background: #eef1f5; }
tr { break-inside: avoid; }
td.practice { width: 30mm; }
.write { height: 26mm; margin: 1mm 0 5mm;
         background: repeating-linear-gradient(to bottom, transparent 0, transparent 8.2mm, #b9c0ca 8.2mm, #b9c0ca 8.5mm); }
.notes { height: 30mm; margin: 2mm 0 6mm; border: 1px dashed #b9c0ca; border-radius: 2mm; position: relative;
         background: repeating-linear-gradient(to bottom, transparent 0, transparent 8.2mm, #e3e7ec 8.2mm, #e3e7ec 8.5mm); }
.notes::before { content: "Notes"; position: absolute; top: -2.6mm; left: 3mm; background: white;
                 padding: 0 1.5mm; font-size: 8.5pt; color: #8a94a3; }
.answers { break-before: page; }
details { margin: 2mm 0 5mm; }
summary { font-weight: 600; list-style: none; margin-bottom: 2mm; color: #1f4e79; }
summary::-webkit-details-marker { display: none; }
hr { display: none; }
p, li, blockquote, .write { break-inside: avoid; }
"""


def md_to_html(md_text: str, is_vocab: bool) -> str:
    # a ruled notes box after every grammar note (### heading inside "Grammar notes")
    if not is_vocab:
        out, in_notes = [], False
        for line in md_text.splitlines():
            if line.startswith("## "):
                if in_notes:
                    out += ['<div class="notes"></div>', ""]
                in_notes = "Grammar notes" in line
            elif line.startswith("### ") and in_notes and any(l.startswith("### ") for l in out[-400:]):
                out += ['<div class="notes"></div>', ""]
            out.append(line)
        md_text = "\n".join(out)

    md = MarkdownIt("commonmark", {"html": True, "breaks": False}).enable("table")
    body = md.render(md_text)

    body = re.sub(r"<p>✏️ _+</p>", '<div class="write"></div>', body)
    body = body.replace("<details>", "<details open>")
    body = re.sub(r"<p><em>Try the exercises first — click to reveal\.</em></p>", "", body)
    body = re.sub(r'(<h2>[^<]*Answer key</h2>)', r'<div class="answers"></div>\1', body)
    if is_vocab:
        body = body.replace("<th>Meaning</th>", "<th>Meaning</th><th>✍︎ Practice</th>")
        body = re.sub(r"(<tr>(?:(?!</tr>).)*?<td>(?:(?!</tr>).)*?)</tr>",
                      lambda m: m.group(1) + '<td class="practice"></td></tr>', body, flags=re.S)
        # each unit starts on a new page
        body = re.sub(r"(<h2>)", r'<div style="break-before: page"></div>\1', body)
        body = body.replace('<div style="break-before: page"></div><h2>', "<h2>", 1)
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


def to_pdf(md_path: Path) -> Path:
    md_text = md_path.read_text(encoding="utf-8")
    html = md_to_html(md_text, is_vocab=md_path.name.startswith("vocabulary"))
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    html_path = HTML_DIR / (re.sub(r"[^\w.-]+", "_", str(md_path.relative_to(paths.STUDY))) + ".html")
    html_path.write_text(html, encoding="utf-8")
    pdf_path = paths.PDF / md_path.relative_to(paths.STUDY).with_suffix(".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                   check=True, capture_output=True)
    return pdf_path


def main() -> None:
    targets = [Path(a) for a in sys.argv[1:]] or sorted(paths.STUDY.rglob("*.md"))
    for md_path in targets:
        pdf = to_pdf(md_path.resolve())
        print(f"{md_path} -> {pdf.relative_to(paths.ROOT)}")


if __name__ == "__main__":
    main()
