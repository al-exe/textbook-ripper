---
name: add-textbook
description: Add a new textbook PDF to textbook-ripper and extract its data (OCR text + per-unit vocabulary with pinyin, part of speech and meaning). Use when the user drops a new PDF in textbooks/ or asks to "add / rip / import a textbook".
---

# Add a textbook

Pipeline: `textbooks/<Book>.pdf` → `ripper.py` (OCR cache + full text) → `vocab.py`
(per-unit vocabulary) → `study.py` (section map, study materials).
Everything is keyed by the PDF's file name without `.pdf` ("Chinese 5").

## 0. One-time setup (fresh machine)

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
mkdir -p tools/data && curl -sSL -o tools/data/cedict.zip https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip && unzip -o tools/data/cedict.zip -d tools/data
```
OCR uses Apple Vision, so it only runs on macOS.

## 1. OCR the book

1. Put the PDF in `textbooks/` with a short name (`Chinese 5.pdf`).
2. Run in the background (≈1 s/page, cached per page in `tools/cache/<Book>/ocr/`; re-runs skip done pages):
   ```bash
   .venv/bin/python tools/ripper.py "textbooks/Chinese 5.pdf"
   ```
   Output: `tools/cache/<Book>/<Book>.txt` (copied to `study/<Book>/full-text.txt`) (page-marked text). Use `--pages 1-20` for a quick sample,
   `--force` to redo pages.
3. Spot-check 2–3 pages of the .txt against page images
   (`.venv/bin/python tools/study.py images "<Book>" 21 22` then Read the PNGs).

## 2. Check the unit structure

```bash
.venv/bin/python tools/study.py sections "<Book>"
```
Every unit should show a title page and the usual sections. The New Target Chinese series
(books 3 & 4) is the reference layout. For a different series, adjust:
- `tools/study.py` → `SECTION_PATTERNS`, `unit_starts()` (how a unit title page is recognised)
- `tools/vocab.py` → `find_pages(book, r"VOCABULARY LIST")` (the vocab-table heading),
  `HEADING_END` (headings that end a vocab table), `PROPER`, `POS_INFO`
  (add any part-of-speech labels the book's abbreviation table lists).

## 3. Extract vocabulary

```bash
.venv/bin/python tools/vocab.py
```
Writes `study/<Book>/vocabulary.md` and `study/vocabulary.csv` (all books).

**Verify — don't skip:**
1. Row counts: for each unit, the last row number printed in the book's vocab table must equal the
   number of rows extracted. Quick check:
   ```bash
   .venv/bin/python -c 'import csv,collections; r=list(csv.DictReader(open("study/vocabulary.csv",encoding="utf-8-sig"))); print(sorted(collections.Counter((x["book"],int(x["unit"]),x["section"]) for x in r).items()))'
   ```
   and compare against the page images of each "生词大盘点 VOCABULARY LIST".
2. Rows with ⚠ / a `review` note: open the page image (`pdf_page` column), check characters,
   pinyin, POS, meaning. When the output is right, or to correct it, add a line to
   `tools/vocab_overrides.csv` (`book,unit,section,no,field,value`; field = chars | pinyin | pos | meaning).
3. Missing POS: many phrases legitimately have none — confirm on the page before overriding.

How the checks work (useful when debugging): characters and pinyin are OCR'd independently; a
row is trusted when CC-CEDICT's pinyin for the characters matches the OCR'd pinyin letters.
Tones come from the dictionary (OCR confuses macron/caron), overridden by the book only when two
OCR reads agree on a valid reading. Missing cells are re-OCR'd from enlarged crops
(`tools/cache/<Book>/cells.json` cache).

## 4. Names for pinyin

If the book has recurring characters, add them to `tools/names.txt` (`汉字<TAB>Pinyin`, e.g.
`大龙	Dàlóng`) so generated pinyin capitalises them correctly.

## 5. PDFs

```bash
.venv/bin/python tools/pdf.py "study/<Book>/vocabulary.md"     # or no args: every study/**/*.md
```
Writes `pdf/<Book>/vocabulary.pdf` (one unit per page, plus a blank practice column for
handwriting on the iPad).

## 6. Report

Tell the user: pages OCR'd, units found, words per unit, anything still flagged, and where the
files are (study/ for Markdown, pdf/ for PDFs). Remember the standing rule: **every Chinese
string in study output must have pinyin.** Next step is usually the `study-material` skill
(grammar sheets per unit).
