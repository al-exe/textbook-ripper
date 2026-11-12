---
name: study-material
description: Turn part of a ripped textbook into a self-contained study sheet (Markdown + matching iPad PDF, with Chinese, word-aligned pinyin, English, exercises and an answer key). Use when the user asks for grammar/sentence-pattern sheets, dialogues, quizzes, culture notes, brainstorm vocab, or "make study material from unit N / pages X–Y" of a book in textbooks/.
---

# Make study material

Output: `study/<Book>/<kind>/unit-NN-<english-title>.md` and its PDF twin
`pdf/<Book>/<kind>/unit-NN-<english-title>.pdf`, both generated from a JSON spec in
`tools/specs/<Book>/<kind>-unit-NN.json`. The spec is the source of truth — never hand-edit the
.md or .pdf; change the spec (or the tools) and re-render.

Standing user preferences (also in memory/CLAUDE.md):
- **Every Chinese character must carry pinyin.** The renderer enforces this: each Chinese line
  is emitted as HTML `<ruby>` with the pinyin aligned word-by-word under the characters (like
  the textbook); short labels/headings get “汉字 (pinyin)”; Chinese inside English text is
  annotated inline.
- **PDFs are used on an iPad with handwriting**: they mirror the Markdown but add ruled
  answer lines under every prompt, a ruled Notes box after each grammar note, a wide right
  margin, and the answer key on its own page(s).

Reference example: `tools/specs/Chinese 3/grammar-unit-04.json`. All 20 grammar units of
Chinese 3 and Chinese 4 already exist — read one before writing a new spec.

The book must already be ripped (see the `add-textbook` skill).

## 1. Find the pages

```bash
.venv/bin/python tools/study.py sections "<Book>" <unit>
```
Section → material kind (New Target Chinese layout):
| Section | Kind / use |
|---|---|
| unit title page (重点语句, 语法点) | key sentences + list of grammar points |
| 任务示范 Task Demonstration | `dialogue` — the lesson text |
| 分步任务活动 Step-by-step tasks | `grammar` — pattern drills ("用‘…’来…") |
| 综合任务活动 Comprehensive tasks | role plays; include in `grammar` only if they drill a pattern (e.g. a fill-in frame) |
| 语法点注释 Grammar notes | `grammar` — explanations + examples |
| 选一选，测一测 | `grammar` quiz — see “Quiz” below |
| 头脑风暴 Brainstorm | `vocab`-style list (book prints pinyin + English) |
| 文化小贴士 Cultural notes | `culture` |
| 录音文本及答案 (back matter) | listening transcripts + official answers — use them (a listening drill becomes “read the transcript, then answer”) |

## 2. Read the material — text AND images

```bash
.venv/bin/python tools/study.py text "<Book>" 69 83          # OCR text (pinyin tones unreliable)
.venv/bin/python tools/study.py images "<Book>" 69 83 --dpi 40 --out <scratchpad dir>
```
Read the PNGs for every page with pictures or garbled OCR (crop with pymupdf for detail). OCR
misses pictures, mangles tone marks and drops lines; the image is the source of truth.
Transcribe the book's own pinyin when it prints one.

## 3. Write the spec

```json
{"book": "Chinese 3", "unit": 4, "kind": "grammar",
 "title": {"zh": "谈住房", "py": "Tán zhùfáng", "en": "Talking about Housing"},
 "source": "PDF pp. 63, 69–83 (printed pp. 47, 53–67)",
 "intro": "English overview…",
 "key_sentences": [{"zh": "…", "py": "…", "en": "…"}],
 "grammar":   [{"title": {"zh","py","en"}, "body": [<blocks>]}],
 "exercises": [{"title": {...}, "activity": {"zh": "两人活动", "py": "…", "en": "Pair work"},
                "instructions": {"zh","py"?,"en"}, "body": [<blocks>],
                "items": [{"picture": "words describing the picture",
                           "prompt": {"zh": "超市里______。", "py": "Chāoshì li ______.", "en": "…"},
                           "answer": [{"zh","py"?,"en"}], "answer_note": "…"}]}],
 "quiz": {"instructions": {...},
          "questions": [{"question": {"zh","py","en"}?, "options": [{"zh","py"}, …],
                         "answer": 0, "explain": "…"}],
          "answer_note": "…"}}
```
Blocks: `text {zh,py?,en}` · `pattern {zh,py?,en}` · `example {zh,py?,en}` (auto-numbered) ·
`dialogue {lines:[{speaker,speaker_py?,zh,py?,en}]}` · `note {en}` · `picture {en}` ·
`list {items:[{zh,py?,en}]}`. Any other `kind` works with the same fields; set `"kind_title"`
for the page header. The output file name comes from `title.en`.

Rules:
- **Include everything needed to learn without the book**: Chinese + English instructions, the
  book's examples, every prompt, and a word description of every picture.
- `py`: the book's printed pinyin when it has one; otherwise omit it (generated). Write numbers
  in `py` the way they're read (`50岁` → `wǔshí suì`) — the aligner maps digit runs onto number
  syllables. Don't put extra explanatory words in `py` (they break alignment) — put them in `en`.
- **Answers go in `answer` fields** → collapsed answer key at the end (own page in the PDF).
  Use the book's answers when it has them (appendix, quiz explanations); otherwise write natural
  model answers using the target pattern, marked “(model answer)”, at the unit's level.
- **Quiz**: the book's “选一选，测一测” is a flowchart — each option says [→②] or [→A–D]. The
  correct option of a question is the one that leads on to another question or to result A;
  the result letters B–D name which grammar point to review → put that in `answer_note`.
- Translate Chinese explanations faithfully; prefer the book's own English when printed.

## 4. Render, review, make the PDF

```bash
.venv/bin/python tools/study.py render "tools/specs/<Book>/grammar-unit-NN.json" --show-generated
.venv/bin/python tools/pdf.py "study/<Book>/grammar/unit-NN-<title>.md"
```
`render` must report no “lines missing pinyin” and no “pinyin doesn't align” lines (an
unaligned line falls back to Chinese + separate pinyin line — fix the spec's `py` so syllables
match the characters). `--show-generated` lists every pinyin string the generator produced:
**review them all**. The generator (`tools/pinyin_util.py`: jieba + CC-CEDICT + textbook rules
for 一/不 sandhi, neutral tones, 儿化, AABB, potential complements…) is good but not perfect —
typical slips are bad word splits and polyphones. Fix one-offs with `py` in the spec; fix
systematic ones with a rule in `pinyin_util.py` (`FIXED`, `EXTRA_WORDS`, `_segment`);
add recurring names to `tools/names.txt`. Quick check: `.venv/bin/python tools/study.py pinyin "句子"`.
Then re-render everything (`for f in tools/specs/*/*.json; do …; done`) and rebuild PDFs
(`.venv/bin/python tools/pdf.py` with no args does all of study/).

## 5. Report

Give the user the .md and .pdf paths, what the sheet covers, and anything you had to guess
(unclear pictures, answers you wrote). For many units, do one, show it, and confirm the format
before batching the rest.
