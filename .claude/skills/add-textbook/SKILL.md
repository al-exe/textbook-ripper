---
name: add-textbook
description: Add a new textbook PDF to textbook-ripper and produce its full set of study resources — OCR full text, per-unit vocabulary (Markdown, CSV, PDF), and grammar & sentence-pattern sheets for every unit (Markdown + iPad PDF). Use when the user drops a new PDF in textbooks/ or asks to "add / rip / import a textbook".
---

# Add a textbook (end-to-end)

What a finished book looks like (Chinese 3 and Chinese 4 are the reference):
```
textbooks/<Book>.pdf                       source scan (git-ignored — keep it local)
study/<Book>/full-text.txt                 OCR text of every page
study/<Book>/vocabulary.md                 vocabulary by unit: character | pinyin | POS | meaning
study/vocabulary.csv                       all books' vocabulary (spreadsheet / Anki)
study/<Book>/grammar/unit-NN-<title>.md    one grammar & sentence-pattern sheet per unit
pdf/<Book>/…                               a PDF twin of every .md above (iPad, room to write)
tools/specs/<Book>/grammar-unit-NN.json    the hand-written source of each grammar sheet
tools/cache/<Book>/                        OCR cache (committed — OCR needs a Mac and takes minutes)
```
Everything is keyed by the PDF's file name without `.pdf` (e.g. "Chinese 5").

Standing user preferences: **every Chinese character in study output carries pinyin**
(word-aligned under the characters in sentences); **PDFs are for handwriting on an iPad**;
file names include the English unit title; PDFs live in `pdf/`, mirroring `study/`.

## 0. One-time setup (fresh machine)

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
# CC-CEDICT is committed at tools/data/cedict_ts.u8; to refresh it:
curl -sSL -o tools/data/cedict.zip https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip && unzip -o tools/data/cedict.zip -d tools/data
```
Needs macOS (Apple Vision OCR) and Google Chrome (PDFs). Textbook scans are git-ignored —
copy them into `textbooks/` on each machine.

## 1. OCR the book

1. Put the PDF in `textbooks/` with a short name (`Chinese 5.pdf`).
2. Run in the background (≈1 s/page; cached per page; re-runs skip finished pages):
   ```bash
   .venv/bin/python tools/ripper.py "textbooks/Chinese 5.pdf"
   ```
   Writes `tools/cache/<Book>/` and `study/<Book>/full-text.txt`. `--pages 1-20` for a sample,
   `--force` to redo pages.
3. Spot-check a few pages of the text against page images
   (`.venv/bin/python tools/study.py images "<Book>" 21 22 --out <scratchpad>`, then Read the PNGs).

## 2. Check the unit structure

```bash
.venv/bin/python tools/study.py sections "<Book>"
```
Every unit should show a title page, the vocabulary list, step-by-step tasks, grammar notes and
the self-test. For a different series than New Target Chinese, adapt:
- `tools/study.py` → `SECTION_PATTERNS`, `unit_starts()` (how a unit title page is recognised)
- `tools/vocab.py` → `find_pages(book, r"VOCABULARY LIST")`, `HEADING_END`, `PROPER`, `POS_INFO`
  (add any part-of-speech labels from the book's abbreviation table)

## 3. Vocabulary

```bash
.venv/bin/python tools/vocab.py
```
Writes `study/<Book>/vocabulary.md` and `study/vocabulary.csv`.

**Verify — don't skip:**
1. Row counts per unit must equal the last row number printed in each “生词大盘点 VOCABULARY
   LIST” (and its 专有名词 Proper Nouns table). Count with:
   ```bash
   .venv/bin/python -c 'import csv,collections; r=list(csv.DictReader(open("study/vocabulary.csv",encoding="utf-8-sig"))); print(sorted(collections.Counter((x["book"],int(x["unit"]),x["section"]) for x in r).items()))'
   ```
   Find the true counts from the page images (tables often continue onto the next page).
2. Compare a few units row by row against the page images (characters, pinyin, POS, meaning).
3. Rows with ⚠ / a `review` note: check the page (`pdf_page` column). To confirm or correct,
   add a line to `tools/vocab_overrides.csv` (`book,unit,section,no,field,value`; field = chars |
   pinyin | pos | meaning) and re-run.
4. Missing POS: many phrases legitimately have none — confirm on the page before overriding.

How it works (for debugging): characters and pinyin are OCR'd independently; a row is trusted
when CC-CEDICT's pinyin for the characters matches the OCR'd pinyin letters. Tones come from the
dictionary (OCR confuses macron/caron), overridden by the book only when two OCR reads agree on a
valid reading. Missing cells are re-OCR'd from enlarged crops (`tools/cache/<Book>/cells.json`).

## 4. Names

Add the book's recurring characters to `tools/names.txt` (`汉字<TAB>Pinyin`, e.g. `大龙	Dàlóng`)
so generated pinyin capitalises and segments them correctly.

## 5. Grammar sheets for every unit

Follow the **study-material** skill for each unit (`kind: grammar`). Do one unit first, show it,
confirm the format, then do the rest.

## 6. PDFs

```bash
.venv/bin/python tools/pdf.py                 # every study/**/*.md -> pdf/
```

## 7. Report (and commit if asked)

Tell the user: pages OCR'd, units found, words per unit, anything still flagged, which sheets
exist, and where (study/ for Markdown, pdf/ for PDFs). The project is a git repo — commit only
when the user asks (their identity is git's default on this machine; don't change git config).
