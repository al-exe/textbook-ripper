# Textbook Ripper

Turn scanned Chinese textbook PDFs into study materials with tone-marked pinyin. The repository contains vocabulary lists, grammar and sentence-pattern sheets, and matching PDFs with room to write on an iPad.

## Browse the study materials

- [Chinese 3 vocabulary](study/Chinese%203/vocabulary.md) · [grammar sheets](study/Chinese%203/grammar/) · [handwriting PDFs](pdf/Chinese%203/)
- [Chinese 4 vocabulary](study/Chinese%204/vocabulary.md) · [grammar sheets](study/Chinese%204/grammar/) · [handwriting PDFs](pdf/Chinese%204/)
- [Combined vocabulary CSV](study/vocabulary.csv) for spreadsheets or Anki

Every Chinese phrase in the study sheets has tone-marked pinyin. Sentences use word-aligned pinyin, which the PDFs place beneath the characters. The PDFs mirror the Markdown sheets and add writing lines, notes space, and a practice column for vocabulary.

## How it works

1. `tools/ripper.py` reads scanned pages with Apple Vision OCR and caches each page's results. It uses separate Chinese/English and Latin OCR passes to help preserve pinyin.
2. `tools/vocab.py` extracts vocabulary tables, checks readings against CC-CEDICT, and writes per-book Markdown plus a combined CSV. Ambiguous rows can be corrected in `tools/vocab_overrides.csv`.
3. Grammar sheets are **curated in JSON specs** under `tools/specs/`. `tools/study.py` renders them as Markdown, adding pinyin where needed. OCR and generated pinyin still need review against the textbook.
4. `tools/pdf.py` renders the Markdown sheets as PDFs for handwriting practice.

## Requirements

- macOS for Apple Vision OCR
- Python 3.10+ and the packages in `tools/requirements.txt`
- Google Chrome at `/Applications/Google Chrome.app` for PDF rendering

The CC-CEDICT dictionary is included at `tools/data/cedict_ts.u8`. Source textbook scans are kept locally in `textbooks/` and are excluded from Git.

## Quick start

Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt

# Add your own scan as textbooks/Chinese 3.pdf, then OCR it.
.venv/bin/python tools/ripper.py "textbooks/Chinese 3.pdf"

# Build vocabulary from the OCR cache.
.venv/bin/python tools/vocab.py

# Inspect the unit page map, then render the curated study-sheet specs.
.venv/bin/python tools/study.py sections "Chinese 3"
.venv/bin/python tools/study.py render

# Make PDF copies of the Markdown sheets.
.venv/bin/python tools/pdf.py
```

Use `--pages 1-20` with `ripper.py` to OCR a sample; completed pages are cached for later runs. To render one grammar spec or one PDF, pass its path to `study.py render` or `pdf.py` respectively.

## Repository layout

```text
textbooks/              Local source scans (Git-ignored)
tools/cache/<Book>/     OCR results and extracted page text
tools/specs/<Book>/     Curated JSON sources for study sheets
tools/                  OCR, vocabulary, pinyin, rendering, and PDF scripts
study/<Book>/           Markdown vocabulary, grammar sheets, and OCR text
study/vocabulary.csv   Combined vocabulary
pdf/<Book>/             PDF copies of the Markdown study sheets
```

For the detailed workflows, see [adding a textbook](.claude/skills/add-textbook/SKILL.md) and [making a study sheet](.claude/skills/study-material/SKILL.md).
