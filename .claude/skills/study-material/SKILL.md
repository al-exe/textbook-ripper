---
name: study-material
description: Turn part of a ripped textbook into a self-contained study sheet (Markdown + matching iPad PDF, with Chinese, word-aligned pinyin, English, exercises and an answer key). Use when the user asks for grammar/sentence-pattern sheets, dialogues, quizzes, culture notes, brainstorm vocab, or "make study material from unit N / pages X–Y" of a book in textbooks/.
---

# Make study material

Each sheet is generated from a JSON spec:
```
tools/specs/<Book>/<kind>-unit-NN.json  ──study.py render──▶  study/<Book>/<kind>/unit-NN-<english-title>.md
                                         ──pdf.py──────────▶  pdf/<Book>/<kind>/unit-NN-<english-title>.pdf
```
The spec is the source of truth: never hand-edit the .md or .pdf — change the spec (or the
tools) and re-render. The output file name comes from `title.en`.

**Standing user preferences** (also in CLAUDE.md):
- **Every Chinese character carries pinyin.** The renderer enforces it: each Chinese sentence
  becomes HTML `<ruby>` with pinyin aligned word-by-word (under the characters in the PDF, like
  the textbook); short labels/headings get “汉字 (pinyin)”; Chinese inside English is annotated.
- **PDFs are for handwriting on an iPad**: same content as the .md, plus ruled answer lines under
  every prompt, a ruled Notes box after each grammar note, a wide right margin, answer key on its
  own page(s).

**Reference**: all 20 grammar units of Chinese 3 and Chinese 4 exist — read
`tools/specs/Chinese 3/grammar-unit-04.json` (and one Chinese 4 spec) before writing a new one,
and match their depth.

The book must already be ripped (see the `add-textbook` skill).

## What a grammar sheet contains

1. **Key sentences** (重点语句, from the unit title page) — Chinese, pinyin, English.
2. **Grammar notes** (语法点注释) — every note in full: the book's Chinese explanation + its
   English, a `pattern` block (formula), the book's examples, and a `note` (💡) with the common
   mistake (take these from the self-test's wrong options). Add short extra sections only for
   patterns the unit clearly drills or the self-test checks (e.g. 之一, 对……感兴趣, 只 placement),
   marked as not being numbered book notes.
3. **Practice** — the step-by-step tasks (分步任务活动) that drill a pattern: activity type,
   Chinese + English instructions, the book's examples, every prompt, a word description of every
   picture, and an answer for every item. Include a comprehensive task only if it drills the
   unit's patterns (e.g. a fill-in frame or role-play frame). Skip pure surveys/debates/listening
   with no transcript.
4. **Self-test** (选一选，测一测) as a plain A/B quiz.
5. **Answer key** — generated from the `answer` fields.

## Per-unit checklist

1. **Find the pages**
   ```bash
   .venv/bin/python tools/study.py sections "<Book>" <unit>
   ```
   Read: the unit title page, step-by-step tasks (up to the comprehensive tasks), grammar notes,
   the self-test page(s) and the results page after it.
2. **Read the OCR text** (Chinese is reliable; pinyin tones and some lines are not):
   ```bash
   .venv/bin/python tools/study.py text "<Book>" <first> <last>
   .venv/bin/python tools/study.py appendix "<Book>" <unit>     # transcripts + answers, if the book has them
   ```
3. **Look at the pages** for every picture, table or line the OCR garbled:
   ```bash
   .venv/bin/python tools/study.py images "<Book>" <page> --dpi 40 --out <scratchpad>
   .venv/bin/python tools/study.py images "<Book>" <page> --crop 0.45 0.95 --dpi 60 --out <scratchpad>
   ```
   then Read the PNGs. The image is the source of truth.
4. **Write the spec** `tools/specs/<Book>/grammar-unit-NN.json` (format below).
5. **Render and review**
   ```bash
   .venv/bin/python tools/study.py render "tools/specs/<Book>/grammar-unit-NN.json" --show-generated
   ```
   Must print no “lines missing pinyin” and no “pinyin doesn't align”. Review **every** line of
   generated pinyin it lists; fix one-offs with `py` in the spec, systematic errors with a rule in
   `tools/pinyin_util.py` (then re-render all specs: `study.py render` with no arguments).
6. **PDF**: `.venv/bin/python tools/pdf.py "study/<Book>/grammar/unit-NN-<title>.md"`; glance at a
   page (render with pymupdf) if layout changed.

For a whole book: do unit 1, show the user, confirm, then units 2–N, then
`study.py render` and `pdf.py` (no args) at the end.

## Spec format

```json
{"book": "Chinese 3", "unit": 4, "kind": "grammar",
 "title": {"zh": "谈住房", "py": "Tán zhùfáng", "en": "Talking about Housing"},
 "source": "PDF pp. 63, 69–83 (printed pp. 47, 53–67)",
 "intro": "English overview of the unit's grammar…",
 "key_sentences": [{"zh": "…", "py": "…", "en": "…"}],
 "grammar":   [{"title": {"zh","py","en"}, "body": [<blocks>]}],
 "exercises": [{"title": {...}, "activity": {"zh": "两人活动", "py": "liǎng rén huódòng", "en": "Pair work"},
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
`list {items:[{zh,py?,en}]}`. An item may have `picture`, `prompt` (zh optional — English-only
prompts are fine for translation drills) or both. Other kinds (`dialogue`, `culture`, …) use the
same fields; set `"kind_title"` for the header.

## Content rules

- **Learnable without the book**: Chinese + English instructions, the book's examples, every
  prompt, every picture described in words.
- **Pinyin (`py`)**: copy the book's printed pinyin where it exists (examples, prompts, quiz
  options, key sentences); omit `py` elsewhere and let the generator fill it. Write numbers as
  read (`50岁` → `wǔshí suì`; `60%` → `bǎi fēn zhī liùshí`) — the aligner maps digit runs onto
  number syllables. Never put extra explanation words in `py` (they break alignment); use `en`.
- **Answers**: the book's when it has them (appendix, matching tasks with a determinable answer,
  quiz); otherwise natural model answers that use the target pattern and only the unit's level
  of vocabulary, ending “(model answer)” in `en`. Every item gets an answer.
- **Quiz**: the book's “选一选，测一测” is a flowchart — each option is tagged [→②] or [→A–D]. The
  correct option leads on to another question or to result A; results B–D say which grammar
  note to review → summarise in `answer_note`. Copy the question line (if any) into `question`.
- **English**: prefer the book's own English for instructions and grammar notes; translate the
  rest faithfully.
- Add any new recurring names to `tools/names.txt`.

## Generated-pinyin pitfalls already handled (don't re-fix)

`tools/pinyin_util.py` (jieba + CC-CEDICT) already handles: 一/不 sandhi; neutral 不 in A不A and
potential complements (吃不下, 找不到, 拿不住); A一A, AA verbs (看看 kànkan), AABB (漂漂亮亮);
儿化; 个 / 里 / 边 / 子 neutral forms; 为 = wéi after 通常/形式…; capitalisation of names,
languages and speaker labels; `FIXED` readings (谁 shéi, 看来 kànlái, 怪不得 guàibude, 可不 kěbù,
不得了 bùdéliǎo, 好处 hǎochù …). Common remaining slips: unusual jieba splits and polyphones —
fix with `py`.

## Report

Give the user the .md and .pdf paths, what each sheet covers, and anything you had to guess
(unclear pictures, answers you wrote). Commit only if the user asks.
