#!/usr/bin/env python3
"""Extract text from scanned Chinese textbooks (Chinese + pinyin + English).

The PDFs are image-only scans, so text is recovered with Apple's Vision OCR
(macOS only, runs locally). Each page is OCR'd twice:

  pass A  zh-Hans + en-US  -> good Chinese and English, but pinyin tone marks are lost
  pass B  en-US only       -> keeps most pinyin tone marks

Latin-only boxes from pass A are replaced with the overlapping pass B text, and
Vision's look-alike marks are mapped back to pinyin (ã -> ā, ă -> ǎ, ...).

Raw OCR results are cached per page as JSON, so re-running only re-does the
layout step unless --force is given.

Usage:
    .venv/bin/python tools/ripper.py                         # all PDFs in textbooks/
    .venv/bin/python tools/ripper.py "textbooks/Chinese 4.pdf" --pages 1-20
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import re
import sys
import time
import unicodedata
from pathlib import Path

import pymupdf

import paths

CJK = re.compile(r"[㐀-鿿豈-﫿]")

# Vision (Latin mode) reads pinyin macrons as tildes and carons as breves.
PINYIN_FIX = str.maketrans({
    "ã": "ā", "ẽ": "ē", "ĩ": "ī", "õ": "ō", "ũ": "ū",
    "Ã": "Ā", "Ẽ": "Ē", "Ĩ": "Ī", "Õ": "Ō", "Ũ": "Ū",
    "ă": "ǎ", "ĕ": "ě", "ĭ": "ǐ", "ŏ": "ǒ", "ŭ": "ǔ",
    "Ă": "Ǎ", "Ĕ": "Ě", "Ĭ": "Ǐ", "Ŏ": "Ǒ", "Ŭ": "Ǔ",
    # circumflex is another common misread of the macron
    "â": "ā", "ê": "ē", "î": "ī", "ô": "ō", "û": "ū",
    "Â": "Ā", "Ê": "Ē", "Î": "Ī", "Ô": "Ō", "Û": "Ū",
})
# Full-width punctuation that Vision emits inside Latin text.
FULLWIDTH_IN_LATIN = str.maketrans({"！": "!", "？": "?", "：": ":", "，": ",", "；": ";",
                                    "（": "(", "）": ")", "［": "[", "］": "]"})


# --------------------------------------------------------------------------- OCR

def _vision_ocr(png: bytes, languages: list[str]) -> list[dict]:
    import Quartz
    import Vision
    from Foundation import NSData

    data = NSData.dataWithBytes_length_(png, len(png))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(languages)
    req.setUsesLanguageCorrection_(False)  # correction mangles pinyin
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {err}")

    boxes = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)[0]
        bb = obs.boundingBox()  # normalized, origin bottom-left
        boxes.append({
            "text": cand.string(),
            "conf": round(float(cand.confidence()), 3),
            # convert to top-left origin: x0, y0, x1, y1 in 0..1
            "bbox": [round(bb.origin.x, 5),
                     round(1 - bb.origin.y - bb.size.height, 5),
                     round(bb.origin.x + bb.size.width, 5),
                     round(1 - bb.origin.y, 5)],
        })
    return boxes


def ocr_page(args: tuple[str, int, float]) -> tuple[int, dict]:
    pdf_path, index, scale = args
    with pymupdf.open(pdf_path) as doc:
        png = doc[index].get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")
    return index, {
        "page": index + 1,
        "cjk_pass": _vision_ocr(png, ["zh-Hans", "en-US"]),
        "latin_pass": _vision_ocr(png, ["en-US"]),
    }


# ----------------------------------------------------------------------- merging

def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def clean_latin(text: str) -> str:
    return text.translate(PINYIN_FIX).translate(FULLWIDTH_IN_LATIN)


def merge_passes(page: dict) -> list[dict]:
    """Combine both OCR passes into one list of boxes."""
    a_boxes = page["cjk_pass"]
    cjk = [b for b in a_boxes if CJK.search(b["text"])]
    latin = [b for b in a_boxes if not CJK.search(b["text"])]
    replaced: set[int] = set()
    accepted: list[dict] = []

    for b in page["latin_pass"]:
        bb = b["bbox"]
        b_area = _area(bb) or 1e-9
        # Latin pass turns Chinese into garbage; ignore anything sitting on CJK text.
        if any(_overlap(bb, c["bbox"]) > 0.3 * min(b_area, _area(c["bbox"]) or 1e-9) for c in cjk):
            continue
        hits = [i for i, a in enumerate(latin)
                if _overlap(bb, a["bbox"]) > 0.5 * (_area(a["bbox"]) or 1e-9)]
        if not hits:
            continue
        # never let one Latin-pass box swallow several stacked lines
        tallest = max(latin[i]["bbox"][3] - latin[i]["bbox"][1] for i in hits)
        if bb[3] - bb[1] > 1.6 * tallest:
            continue
        replaced.update(hits)
        accepted.append({**b, "text": clean_latin(b["text"])})

    kept = [{**a, "text": clean_latin(a["text"])} for i, a in enumerate(latin) if i not in replaced]
    # NFC maps CJK compatibility ideographs (e.g. U+2F825) to the normal characters
    return [{**b, "text": unicodedata.normalize("NFC", b["text"])} for b in cjk + kept + accepted]


# ------------------------------------------------------------------------ layout

def strip_chrome(boxes: list[dict]) -> tuple[list[dict], str | None]:
    """Remove running header and left sidebar; return printed page number if found."""
    body, page_no = [], None
    for b in boxes:
        x0, y0, x1, y1 = b["bbox"]
        t = b["text"].strip()
        if y1 < 0.09:  # running header band ("New Target Chinese…", "Unit 3 Talking about…")
            continue
        if x1 < 0.085 or x0 > 0.92:  # sidebars (vertical title, page no., reader UI)
            if x1 < 0.085 and re.fullmatch(r"\d{1,3}", t):
                page_no = t
            continue
        if re.fullmatch(r"[+＋]", t):
            continue
        body.append(b)
    return body, page_no


def layout(boxes: list[dict]) -> str:
    """Group boxes into reading-order lines and paragraphs."""
    if not boxes:
        return ""
    boxes = sorted(boxes, key=lambda b: ((b["bbox"][1] + b["bbox"][3]) / 2, b["bbox"][0]))
    lines: list[list[dict]] = []
    for b in boxes:
        cy = (b["bbox"][1] + b["bbox"][3]) / 2
        h = b["bbox"][3] - b["bbox"][1]
        if lines:
            ref = lines[-1]
            ry = sum((r["bbox"][1] + r["bbox"][3]) / 2 for r in ref) / len(ref)
            rh = min(r["bbox"][3] - r["bbox"][1] for r in ref)
            if abs(cy - ry) < 0.5 * min(h, rh):
                ref.append(b)
                continue
        lines.append([b])

    out, prev_bottom, prev_h = [], None, None
    for line in lines:
        line.sort(key=lambda b: b["bbox"][0])
        top = min(b["bbox"][1] for b in line)
        bottom = max(b["bbox"][3] for b in line)
        h = bottom - top
        if prev_bottom is not None and top - prev_bottom > 1.2 * max(h, prev_h):
            out.append("")
        parts, last_x1 = [], None
        for b in line:
            if last_x1 is not None:
                gap = b["bbox"][0] - last_x1
                parts.append("    " if gap > 0.04 else " ")
            parts.append(b["text"].strip())
            last_x1 = b["bbox"][2]
        out.append("".join(parts))
        prev_bottom, prev_h = bottom, h
    return "\n".join(out)


# -------------------------------------------------------------------------- main

def parse_pages(spec: str | None, count: int) -> list[int]:
    if not spec:
        return list(range(count))
    pages: set[int] = set()
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        pages.update(range(int(lo) - 1, min(int(hi or lo), count)))
    return sorted(p for p in pages if 0 <= p < count)


def process(pdf: Path, out_root: Path, pages_spec: str | None, workers: int,
            scale: float, force: bool, keep_chrome: bool) -> None:
    with pymupdf.open(pdf) as doc:
        count = doc.page_count
    pages = parse_pages(pages_spec, count)
    book_dir = out_root / pdf.stem
    cache_dir = book_dir / "ocr"
    cache_dir.mkdir(parents=True, exist_ok=True)

    todo = [i for i in pages if force or not (cache_dir / f"{i + 1:04d}.json").exists()]
    print(f"{pdf.name}: {count} pages, {len(pages)} selected, {len(todo)} to OCR", flush=True)
    if todo:
        t0 = time.time()
        jobs = [(str(pdf), i, scale) for i in todo]
        ctx = mp.get_context("spawn")  # PyObjC is not fork-safe
        with ctx.Pool(workers) as pool:
            for n, (i, result) in enumerate(pool.imap_unordered(ocr_page, jobs), 1):
                (cache_dir / f"{i + 1:04d}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"\r  OCR {n}/{len(todo)}  ({time.time() - t0:.0f}s)", end="", flush=True)
        print(flush=True)

    chunks = []
    for i in pages:
        page = json.loads((cache_dir / f"{i + 1:04d}.json").read_text(encoding="utf-8"))
        boxes = merge_passes(page)
        printed = None
        if not keep_chrome:
            boxes, printed = strip_chrome(boxes)
        header = f"===== PDF page {i + 1}" + (f" (printed p. {printed})" if printed else "") + " ====="
        chunks.append(f"{header}\n{layout(boxes)}\n")

    suffix = f".p{pages_spec}" if pages_spec else ""
    out_file = book_dir / f"{pdf.stem}{suffix}.txt"
    out_file.write_text("\n".join(chunks), encoding="utf-8")
    print(f"  -> {out_file}")
    if not pages_spec:  # the full book's text is also a study material
        study_copy = paths.STUDY / pdf.stem / "full-text.txt"
        study_copy.parent.mkdir(parents=True, exist_ok=True)
        study_copy.write_text("\n".join(chunks), encoding="utf-8")
        print(f"  -> {study_copy}")


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("This tool uses Apple Vision OCR and only runs on macOS.")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*", type=Path, help="PDF files (default: textbooks/*.pdf)")
    ap.add_argument("-o", "--out", type=Path, default=paths.CACHE, help="cache folder (default: tools/cache/)")
    ap.add_argument("-p", "--pages", help="page selection, 1-based, e.g. '1-10,15'")
    ap.add_argument("-w", "--workers", type=int, default=4, help="parallel OCR processes (default: 4)")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="render scale relative to the scan's native size (default: 1.0)")
    ap.add_argument("--force", action="store_true", help="re-OCR pages even if cached")
    ap.add_argument("--keep-chrome", action="store_true",
                    help="keep running headers and sidebar text")
    args = ap.parse_args()

    pdfs = args.pdfs or sorted(paths.TEXTBOOKS.glob("*.pdf"))
    if not pdfs:
        sys.exit("No PDFs given and none found in textbooks/")
    for pdf in pdfs:
        process(pdf, args.out, args.pages, args.workers, args.scale, args.force, args.keep_chrome)


if __name__ == "__main__":
    main()
