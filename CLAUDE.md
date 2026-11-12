# textbook-ripper

Turns scanned Chinese textbooks (PDFs in `textbooks/`) into study materials (`study/`, with PDF
twins in `pdf/` for handwriting on the iPad).

## Standing rule
Every Chinese character in study output must be accompanied by tone-marked pinyin —
titles, headings, POS labels, Chinese inside English text, everything. Sentences use word-aligned
pinyin (HTML ruby, pinyin under the characters like the textbook). PDFs leave room to write.

## Layout
```
textbooks/                 source PDFs
study/                     everything the learner uses
  vocabulary.csv           all books' vocabulary (spreadsheet / Anki)
  <Book>/vocabulary.md     per-unit vocabulary
  <Book>/grammar/unit-NN-<title>.md   grammar & sentence-pattern sheets
  <Book>/full-text.txt     raw OCR text of the whole book
pdf/                       PDF versions of study/ (same layout) — ruled answer space, notes boxes
tools/                     code and supporting data (run from the repo root)
  ripper.py                Apple Vision OCR (macOS) → tools/cache/<Book>/
  vocab.py                 vocabulary tables → study/; fixes in tools/vocab_overrides.csv
  study.py                 section map, page text/images, render specs → study/
  pdf.py                   study/*.md -> pdf/*.pdf via headless Chrome
  pinyin_util.py           textbook-style sentence pinyin (jieba + CC-CEDICT + sandhi rules) + ruby alignment
  paths.py                 all paths in one place
  specs/<Book>/<kind>-unit-NN.json   hand-written study-sheet specs (source of truth)
  cache/<Book>/            OCR cache (ocr/NNNN.json), page text, cell re-reads
  data/cedict_ts.u8        CC-CEDICT dictionary
  names.txt                character names for pinyin (汉字<TAB>Pinyin)
```

## Skills
- `add-textbook` — import and rip a new PDF, extract + verify vocabulary
- `study-material` — make study sheets (grammar patterns, dialogues, quizzes…) from any part of a book

## Commands (from the repo root)
```bash
.venv/bin/python tools/ripper.py ["textbooks/X.pdf"] [--pages 1-20]
.venv/bin/python tools/vocab.py
.venv/bin/python tools/study.py sections "Chinese 3" 4
for f in tools/specs/*/*.json; do .venv/bin/python tools/study.py render "$f"; done
.venv/bin/python tools/pdf.py              # rebuild all PDFs
```
