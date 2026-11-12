#!/usr/bin/env python3
"""Build per-unit vocabulary lists from the OCR cache produced by ripper.py.

For every unit's "生词大盘点 VOCABULARY LIST" table (and its "专有名词 Proper
Nouns" table) this extracts: character(s), pinyin, part of speech, meaning.
Every piece of Chinese in the output (unit titles, POS labels, Chinese inside
meanings) is given pinyin too.

How each row is checked
-----------------------
OCR'd pinyin tone marks are unreliable, so the pinyin is taken from the
CC-CEDICT dictionary (data/cedict_ts.u8, pypinyin as fallback) with 一/不
tone sandhi applied, choosing between alternative readings using the book's
OCR'd pinyin as evidence. Spacing follows the book.

The OCR'd characters and the OCR'd pinyin are two independent reads, so when
the dictionary pinyin of the characters matches the OCR'd pinyin letters, the
row is very likely right. When it doesn't:
  1. the row's character cell is re-OCR'd from a cropped, enlarged image;
  2. failing that, a dictionary word with matching pinyin that shares
     characters with the OCR text is substituted (e.g. 容气 -> 客气);
  3. failing that, the row is flagged in the `review` column.

Manual fixes can be put in vocab_overrides.csv
(columns: book,unit,section,no,field,value — field is chars/pinyin/pos/meaning).

Usage:
    .venv/bin/python tools/vocab.py      # writes study/<book>/vocabulary.md and study/vocabulary.csv
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

import pymupdf
from pypinyin import Style, pinyin

import paths
import ripper

OUT_ROOT = paths.CACHE
PDF_ROOT = paths.TEXTBOOKS
VOCAB_DIR = paths.STUDY  # study/<book>/vocabulary.md, study/vocabulary.csv
CEDICT = paths.CEDICT
OVERRIDES = paths.OVERRIDES

# Chinese POS abbreviation -> (pinyin, English)
POS_INFO = {
    "名": ("míng", "noun"), "动": ("dòng", "verb"), "形": ("xíng", "adjective"),
    "副": ("fù", "adverb"), "量": ("liàng", "measure word"), "连": ("lián", "conjunction"),
    "代": ("dài", "pronoun"), "介": ("jiè", "preposition"), "助": ("zhù", "particle"),
    "数": ("shù", "numeral"), "叹": ("tàn", "interjection"), "拟声": ("nǐshēng", "onomatopoeia"),
    "象声": ("xiàngshēng", "onomatopoeia"), "能愿": ("néngyuàn", "modal verb"),
    "助动": ("zhùdòng", "auxiliary verb"), "数量": ("shùliàng", "numeral-measure word"),
    "专名": ("zhuānmíng", "proper noun"),
    "结构助词": ("jiégòu zhùcí", "structural particle"), "动态助词": ("dòngtài zhùcí", "aspect particle"),
    "语气助词": ("yǔqì zhùcí", "modal particle"), "助词": ("zhùcí", "particle"),
    "代词": ("dàicí", "pronoun"), "疑问代词": ("yíwèn dàicí", "interrogative pronoun"),
    "能动": ("néngdòng", "optative verb"), "头": ("tóu", "prefix"), "尾": ("wěi", "suffix"),
}
_POS_ALT = "|".join(sorted(POS_INFO, key=len, reverse=True))
POS_RE = re.compile(rf"^(?:{_POS_ALT})(?:[/、,，]?(?:{_POS_ALT}))*$")  # OCR sometimes drops the slash
_POS_SPLIT = re.compile(rf"{_POS_ALT}")


def normalize_pos(pos: str) -> str:
    """'名形' / '名，形' -> '名/形'; keeps the book's 、 when present."""
    parts = _POS_SPLIT.findall(pos)
    sep = "、" if "、" in pos else "/"
    return sep.join(parts)
HEADING_END = re.compile(r"TASKS|ACTIVITIES|任务|Task Demo|评估|EVALUATION|注释|GRAMMAR|WARM-UP|导入")
PROPER = re.compile(r"专有名词|Proper Nouns?\b", re.I)
CJK = ripper.CJK

# ======================================================================= tables


@dataclass
class Row:
    num: str = ""
    chars: str = ""
    pinyin: str = ""      # OCR text of the pinyin cell
    pos: str = ""
    meaning: str = ""
    unit: str = ""        # glossary only
    page: int = 0
    section: str = "main"
    cell: tuple = ()      # (x0, y0, x1, y1) of the character cell, page-relative
    pcell: tuple = ()     # same for the pinyin cell
    poscell: tuple = ()   # and the part-of-speech cell (empty if the table has none)


def load_boxes(book: str, page: int) -> list[dict]:
    data = json.loads((OUT_ROOT / book / "ocr" / f"{page:04d}.json").read_text(encoding="utf-8"))
    boxes, _ = ripper.strip_chrome(ripper.merge_passes(data))
    return boxes


def cy(b):
    return (b["bbox"][1] + b["bbox"][3]) / 2


def is_latin(t):
    return not CJK.search(t) and re.search(r"[A-Za-zÀ-ɏ]", t)


def parse_table(boxes: list[dict], page: int, glossary=False) -> list[Row]:
    """Turn boxes inside a table region into rows.

    Columns are located from the data (number | characters | pinyin | POS |
    meaning [| unit]). Rows are found by clustering the vertical positions of
    everything in the number/character/pinyin columns, so a row survives even
    if OCR missed one of its cells.
    """
    cjk_boxes = [b for b in boxes if CJK.search(b["text"])]
    latin_boxes = [b for b in boxes if is_latin(b["text"])]
    if not cjk_boxes or not latin_boxes:
        return []
    # character column = leftmost x0 cluster with >= 2 CJK boxes
    xs = sorted(b["bbox"][0] for b in cjk_boxes)
    char_x = next((x for x in xs if sum(abs(x - y) < 0.03 for y in xs) >= 2), xs[0])
    # pinyin column = first Latin box to the right of each word, on the same line
    firsts = []
    for c in cjk_boxes:
        if abs(c["bbox"][0] - char_x) > 0.03:
            continue
        h = c["bbox"][3] - c["bbox"][1]
        right = [b["bbox"][0] for b in latin_boxes
                 if b["bbox"][0] > c["bbox"][2] and abs(cy(b) - cy(c)) < 0.6 * h]
        if right:
            firsts.append(min(right))
    if not firsts:
        return []
    pin_x = statistics.median(firsts)
    pos_xs = [b["bbox"][0] for b in boxes if POS_RE.match(b["text"].strip()) and b["bbox"][0] > pin_x + 0.05]
    pos_x = statistics.median(pos_xs) if pos_xs else None
    # meaning column = leftmost cluster of Latin boxes clearly right of the pinyin
    mxs = sorted(b["bbox"][0] for b in latin_boxes if b["bbox"][0] > max(pin_x + 0.1, (pos_x or 0) + 0.02))
    mean_x = next((x for x in mxs if sum(abs(x - y) < 0.03 for y in mxs) >= 2), mxs[0] if mxs else 1.0)
    pin_end = min(pos_x or 1.0, mean_x) - 0.015

    def col(b):
        x0, t = b["bbox"][0], b["text"].strip()
        if x0 < char_x - 0.01 and re.fullmatch(r"\d{1,3}", t):
            return "num"
        if glossary and x0 > 0.8 and re.fullmatch(r"\d{1,2}", t):
            return "unit"
        if x0 < pin_x - 0.01:
            return "chars" if CJK.search(t) else None
        if pos_x is not None and abs(x0 - pos_x) < 0.05 and POS_RE.match(t):
            return "pos"
        if x0 < pin_end:
            return "pinyin" if is_latin(t) else None
        return "meaning"

    keyed = [(b, col(b)) for b in boxes]
    keys = sorted((b for b, c in keyed if c in ("num", "chars", "pinyin")), key=cy)
    if not keys:
        return []
    hs = sorted(b["bbox"][3] - b["bbox"][1] for b in keys)
    thresh = 0.6 * hs[len(hs) // 2]
    kind = {id(b): c for b, c in keyed}
    clusters: list[list[dict]] = []
    for b in keys:
        if clusters and cy(b) - statistics.mean(map(cy, clusters[-1])) < thresh:
            clusters[-1].append(b)
        else:
            clusters.append([b])
    # characters with no pinyin or number beside them are a scribble / stray mark
    clusters = [c for c in clusters if {kind[id(b)] for b in c} != {"chars"}]
    if not clusters:
        return []
    # merge lines of one tall row (a wrapped character cell, or a number centred
    # between two lines): they sit much closer together than normal rows do,
    # but two clusters that each carry a row number are always separate rows
    if len(clusters) > 2:
        cs = [statistics.mean(map(cy, c)) for c in clusters]
        pitch = statistics.median([b - a for a, b in zip(cs, cs[1:])])
        merged = [clusters[0]]
        for c in clusters[1:]:
            has_num = lambda g: any(kind[id(b)] == "num" for b in g)
            gap = statistics.mean(map(cy, c)) - statistics.mean(map(cy, merged[-1][-1:]))
            if gap < 0.6 * pitch and not (has_num(c) and has_num(merged[-1])):
                merged[-1] = merged[-1] + c
            else:
                merged.append(c)
        clusters = merged
    rows_c = [statistics.mean(map(cy, c)) for c in clusters]
    # a row needs characters or pinyin (a lone number is just noise)
    groups: list[list[tuple]] = [[] for _ in rows_c]
    for b, c in keyed:
        if c is None:
            continue
        i = min(range(len(rows_c)), key=lambda k: abs(rows_c[k] - cy(b)))
        if abs(rows_c[i] - cy(b)) < 0.035:
            groups[i].append((b, c))

    pitch = statistics.median([b - a for a, b in zip(rows_c, rows_c[1:])]) if len(rows_c) > 1 else 0.03
    out = []
    for c_y, g in zip(rows_c, groups):
        kinds = {c for _, c in g}
        # need characters or pinyin plus one more column (a lone box is noise or a scribble)
        if not kinds & {"chars", "pinyin"} or len(kinds - {"unit"}) < 2:
            continue
        half = min(0.45 * pitch, 0.02)
        row = Row(page=page,
                  cell=(char_x - 0.015, c_y - half, pin_x - 0.01, c_y + half),
                  pcell=(pin_x - 0.01, c_y - half, pin_end, c_y + half),
                  poscell=(pos_x - 0.03, c_y - half, mean_x - 0.01, c_y + half) if pos_x
                  else (mean_x - 0.12, c_y - half, mean_x - 0.01, c_y + half) if mean_x - pin_x > 0.22
                  else ())  # a wide pinyin→meaning gap means a POS column OCR missed entirely
        g.sort(key=lambda bc: (round(cy(bc[0]), 2), bc[0]["bbox"][0]))
        chars, pins, meaning = [], [], []
        for b, c in g:
            t = b["text"].strip()
            if c == "num":
                row.num = t
            elif c == "unit":
                row.unit = t
            elif c == "chars":
                chars.append(b)
            elif c == "pinyin":
                pins.append(t)
            elif c == "pos":
                row.pos = t
            else:
                meaning.append(t)
        # overlapping fragments / handwritten scribbles: the widest box wins
        keep = []
        chars.sort(key=lambda b: (round(cy(b), 2), b["bbox"][0]))
        for b in chars:
            same_line = keep and abs(cy(b) - cy(keep[-1])) < 0.5 * (b["bbox"][3] - b["bbox"][1])
            if same_line and b["bbox"][0] < keep[-1]["bbox"][2] - 0.005:
                if (b["bbox"][2] - b["bbox"][0]) > (keep[-1]["bbox"][2] - keep[-1]["bbox"][0]):
                    keep[-1] = b
                continue
            keep.append(b)
        row.chars = "".join(b["text"].strip() for b in keep)
        row.pinyin = " ".join(pins)
        row.meaning = " ".join(meaning)
        out.append(row)
    return out


def find_pages(book: str, pattern: str, after: int = 20) -> list[int]:
    pages = sorted(int(p.stem) for p in (OUT_ROOT / book / "ocr").glob("*.json"))
    return [p for p in pages if p > after
            and any(re.search(pattern, b["text"], re.I) for b in load_boxes(book, p))]


def extract_unit(book: str, start: int) -> list[Row]:
    rows: list[Row] = []
    section = "main"
    for page in (start, start + 1):
        boxes = sorted(load_boxes(book, page), key=cy)
        if page == start:
            hdr = next(b for b in boxes if re.search(r"VOCABULARY LIST", b["text"], re.I))
            boxes = [b for b in boxes if b["bbox"][1] > hdr["bbox"][3]]
        else:
            # the table continues only if the page opens with a numbered row
            top = [b for b in boxes if boxes and cy(b) - cy(boxes[0]) < 0.07]
            if not any(re.fullmatch(r"\d{1,2}", b["text"].strip()) and b["bbox"][0] < 0.25 for b in top):
                break
        chunk: list[dict] = []
        ended = False
        for b in boxes + [None]:
            t = b["text"] if b else ""
            if b is None or HEADING_END.search(t) or PROPER.search(t):
                for r in parse_table(chunk, page):
                    r.section = section
                    rows.append(r)
                chunk = []
                if b is not None and PROPER.search(t):
                    section = "proper"  # (the 专有名词 and Proper Nouns boxes both land here)
                    continue
                ended = b is not None
                break
            chunk.append(b)
        if ended:
            break
    return rows


def glossary_rows(book: str) -> list[Row]:
    """The back-of-book glossary: a second (partial) read of pinyin / POS."""
    starts = find_pages(book, r"词语总表")
    ends = find_pages(book, r"录音文本|Listening Scripts")
    if not starts:
        return []
    count = len(list((OUT_ROOT / book / "ocr").glob("*.json")))
    last = min([e for e in ends if e > starts[0]] or [count + 1]) - 1
    rows = []
    for p in range(starts[0], min(last, count) + 1):
        boxes = [b for b in load_boxes(book, p) if not re.fullmatch(r"[A-Z]", b["text"].strip())
                 and "词语总表" not in b["text"] and "Vocabulary" not in b["text"]]
        rows += parse_table(boxes, p, glossary=True)
    return rows


_CELL_CACHE: dict = {}


def reocr_cell(book: str, row: Row, which: str = "chars") -> str:
    """Re-OCR just one cell of a row from an enlarged crop (cached)."""
    cache = OUT_ROOT / book / "cells.json"
    if book not in _CELL_CACHE:
        _CELL_CACHE[book] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    store = _CELL_CACHE[book]
    rect = {"chars": row.cell, "pinyin": row.pcell, "pos": row.poscell}[which]
    key = json.dumps(["v2", which, row.page] + [round(v, 3) for v in rect])
    if key not in store:
        text = ""
        with pymupdf.open(PDF_ROOT / f"{book}.pdf") as doc:
            p = doc[row.page - 1]
            W, H = p.rect.width, p.rect.height
            x0, y0, x1, y1 = rect
            for scale in (2, 3, 1.5):  # Vision occasionally misses a lone glyph; retry
                png = p.get_pixmap(matrix=pymupdf.Matrix(scale, scale),
                                   clip=pymupdf.Rect(x0 * W, y0 * H, x1 * W, y1 * H)).tobytes("png")
                if which in ("chars", "pos"):
                    boxes = sorted(ripper._vision_ocr(png, ["zh-Hans"]), key=lambda b: b["bbox"][0])
                    text = "".join(b["text"].strip() for b in boxes if CJK.search(b["text"]))
                else:
                    boxes = sorted(ripper._vision_ocr(png, ["en-US"]), key=lambda b: b["bbox"][0])
                    text = ripper.clean_latin(" ".join(b["text"].strip() for b in boxes))
                if text:
                    break
        store[key] = unicodedata.normalize("NFC", text)
        cache.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    return store[key]


# ======================================================================= pinyin

TONE_MARKS = {"̄": 1, "́": 2, "̌": 3, "̀": 4}
MARK_FOR = {v: k for k, v in TONE_MARKS.items()}
# Vision's Latin model invents marks that look like pinyin tones
MARK_FIX = {"̃": "̄", "̂": "̄", "̆": "̌", "̉": "̌"}
MARK_DROP = {"̛", "̣", "̇"}


def normalize_ocr_pinyin(s: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if ch in MARK_DROP:
            continue
        if ch == "̈" and out and out[-1].lower() != "u":  # ö -> ō
            ch = "̄"
        out.append(MARK_FIX.get(ch, ch))
    res, prev_mark = [], False  # keep only the first tone mark on a letter
    for ch in out:
        is_mark = ch in TONE_MARKS
        if not (is_mark and prev_mark):
            res.append(ch)
        prev_mark = is_mark
    s = unicodedata.normalize("NFC", "".join(res))
    return s.translate(ripper.FULLWIDTH_IN_LATIN).replace("•", "…").replace("⋯", "…")


def split_tone(s: str) -> tuple[str, int]:
    """'xiàn' -> ('xian', 4); 'zi' -> ('zi', 0). Keeps ü."""
    tone, base = 0, []
    for ch in unicodedata.normalize("NFD", s):
        if ch in TONE_MARKS:
            tone = TONE_MARKS[ch]
        else:
            base.append(ch)
    return unicodedata.normalize("NFC", "".join(base)), tone


def add_tone(syl: str, tone: int) -> str:
    if tone == 0:
        return syl
    low = syl.lower()
    if "a" in low:
        i = low.index("a")
    elif "e" in low:
        i = low.index("e")
    elif "ou" in low:
        i = low.index("o")
    else:
        i = max(low.rfind(v) for v in "iouü")
    return unicodedata.normalize("NFC", syl[:i + 1] + MARK_FOR[tone] + syl[i + 1:])


def join_syllables(syls: list[str]) -> str:
    """Join pinyin syllables into one word, adding ' before a/e/o (kù'ài)."""
    out = ""
    for s in syls:
        if out and split_tone(s[:1])[0].lower() in ("a", "e", "o"):
            out += "'"
        out += s
    return out


def num_to_mark(numbered: str) -> tuple[str, int]:
    m = re.fullmatch(r"([a-zü:]+)([1-5])", numbered.lower().replace("u:", "ü"))
    if not m:
        return numbered.lower(), 0
    t = int(m.group(2))
    return m.group(1), 0 if t == 5 else t


CEDICT_DB: dict[str, list] = {}
CEDICT_DEFS: dict[tuple, str] = {}
CEDICT_PROPER: set[str] = set()   # words whose only CEDICT readings are capitalised (中文, 北京)
_CEDICT_LOWER: set[str] = set()
CEDICT_BY_LETTERS: dict[str, list[str]] = defaultdict(list)


def load_cedict() -> None:
    if not CEDICT.exists():
        print(f"warning: {CEDICT} missing; falling back to pypinyin only")
        return
    for line in CEDICT.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\S+ (\S+) \[([^\]]+)\] (.*)", line)
        if not m or line.startswith("#"):
            continue
        word = m.group(1)
        reading = [num_to_mark(x) for x in m.group(2).split()]
        if len(reading) != len(word):
            continue
        if m.group(2)[:1].isupper():
            if word not in _CEDICT_LOWER:
                CEDICT_PROPER.add(word)
        else:
            _CEDICT_LOWER.add(word)
            CEDICT_PROPER.discard(word)
        k = (word, tuple(reading))
        CEDICT_DEFS[k] = CEDICT_DEFS.get(k, "") + " " + m.group(3).lower()
        entries = CEDICT_DB.setdefault(word, [])
        if reading not in entries:
            entries.append(reading)
            CEDICT_BY_LETTERS["".join(b for b, _ in reading).replace("ü", "u")].append(word)


LETTER = re.compile(r"[a-zü]")


def base_letter(c: str) -> str:
    b = split_tone(c)[0].lower()
    return "ü" if b == "v" else b


def is_letter(c: str) -> bool:
    return bool(LETTER.fullmatch(base_letter(c) or " "))


def letters_of(s: str) -> list[tuple[int, str]]:
    return [(i, base_letter(c)) for i, c in enumerate(s) if is_letter(c)]


def align(ocr: str, bases: list[str], fuzzy: bool = False):
    """Map each syllable onto the OCR string.

    Returns per-syllable (tone_seen, start, end) indices into `ocr`, or None.
    Exact mode requires identical letters; fuzzy mode tolerates OCR misreads.
    """
    letters = letters_of(ocr)
    flat = "".join(l for _, l in letters).replace("ü", "u")
    target = "".join(bases).replace("ü", "u")
    if not letters:
        return None
    if flat == target:
        mapping = list(range(len(target)))
    elif fuzzy:
        sm = difflib.SequenceMatcher(None, target, flat, autojunk=False)
        if sm.ratio() < 0.75:
            return None
        mapping = [None] * len(target)
        for a, b, n in sm.get_matching_blocks():
            for k in range(n):
                mapping[a + k] = b + k
    else:
        return None
    out, k = [], 0
    for b in bases:
        js = [mapping[k + j] for j in range(len(b)) if mapping[k + j] is not None]
        lost_first = mapping[k] is None
        k += len(b)
        if not js:
            out.append((0, None, None))
            continue
        idx = [letters[j][0] for j in js]
        seg = "".join(ocr[i] for i in range(idx[0], idx[-1] + 1))
        # tone is -1 when the syllable's first letter was lost (don't trust a space before it)
        out.append((split_tone(seg)[1] if flat == target else (-1 if lost_first else 0), idx[0], idx[-1] + 1))
    return out


def score(reading, aligned_reads) -> float:
    s = 0.0
    for spans in aligned_reads:
        for (_, tone), (seen, _, _) in zip(reading, spans):
            if seen < 0:
                continue
            if seen == tone:
                s += 1
            elif seen and tone and (seen in (1, 3)) == (tone in (1, 3)):
                s += 0.3   # macron/caron and acute/grave are often confused
    return s


def segment(hanzi: str) -> list[str]:
    out, i = [], 0
    while i < len(hanzi):
        for j in range(len(hanzi), i, -1):
            if hanzi[i:j] in CEDICT_DB or j == i + 1:
                out.append(hanzi[i:j])
                i = j
                break
    return out


def candidates(word: str) -> list[list[tuple[str, int]]]:
    cands = list(CEDICT_DB.get(word, []))
    default = [split_tone(x[0]) for x in pinyin(word, style=Style.TONE)]
    if len(word) == 1:
        for p in pinyin(word, style=Style.TONE, heteronym=True)[0]:
            if [split_tone(p)] not in cands:
                cands.append([split_tone(p)])
    if default not in cands:
        cands.append(default)
    if word.endswith("儿") and len(word) > 1:  # 儿化: 哪儿 -> nǎr
        cands += [c[:-1] + [("r", 0)] for c in cands if c[-1][0] == "er"]
    if len(word) == 1 or word not in CEDICT_DB:
        cands.sort(key=lambda c: c != default)  # single chars: pypinyin's most common reading first
    return cands  # words: dictionary readings first, pypinyin's guess last


def sandhi(hanzi: str, syls: list[tuple[str, int]]) -> list[tuple[str, int]]:
    syls = list(syls)
    # potential complements (走不动, 看得见) are printed with a neutral-tone 不/得
    if len(hanzi) == 3 and hanzi[1] in "不得" and hanzi not in CEDICT_DB:
        syls[1] = (syls[1][0], 0)
        return syls
    for i, ch in enumerate(hanzi[:-1]):
        nxt = syls[i + 1][1]
        if ch == "不" and syls[i][0] == "bu" and nxt == 4:
            syls[i] = ("bu", 2)
        elif ch == "一" and syls[i][0] == "yi" and nxt == 4:
            syls[i] = ("yi", 2)
        elif ch == "一" and syls[i][0] == "yi" and nxt in (1, 2, 3):
            syls[i] = ("yi", 4)
    return syls


@dataclass
class Resolved:
    pinyin: str
    match: str            # "exact", "fuzzy" or "none"
    notes: list[str]


STOP = {"the", "and", "for", "with", "one", "who", "that", "this", "used", "sth", "sb", "something", "somebody"}


def meaning_bonus(words: list[str], combo, meaning: str) -> float:
    """Prefer the dictionary reading whose definition shares words with the textbook's meaning."""
    if not meaning:
        return 0.0
    toks = {t for t in re.findall(r"[a-z]{3,}", meaning.lower()) if t not in STOP}
    bonus = 0.0
    for w, reading in zip(words, combo):
        if (w, tuple(reading)) in CEDICT_DEFS:
            defs = set(re.findall(r"[a-z]{3,}", CEDICT_DEFS.get((w, tuple(reading)), "")))
            if toks & defs:
                bonus += 0.8
    return bonus


def resolve_pinyin(chars: str, reads: list[str], proper=False, meaning: str = "") -> Resolved:
    """reads[0] = unit-table OCR pinyin, reads[1] = glossary OCR pinyin (optional)."""
    hanzi = "".join(c for c in chars if CJK.match(c))
    reads = [normalize_ocr_pinyin(r) for r in reads if r]
    if not hanzi:
        return Resolved(reads[0] if reads else "", "none", ["no characters read"])

    words = segment(hanzi)
    best = None
    for combo in product(*(candidates(w) for w in words)):
        reading = sandhi(hanzi, [s for w in combo for s in w])
        bases = [b for b, _ in reading]
        exact = [(r, a) for r in reads if (a := align(r, bases))]
        fuzzy = [(r, a) for r in reads if not align(r, bases) and (a := align(r, bases, fuzzy=True))]
        sc = (10 * len(exact) + 5 * len(fuzzy) + score(reading, [a for _, a in exact])
              + meaning_bonus(words, combo, meaning))
        if best is None or sc > best[0]:
            best = (sc, reading, exact, fuzzy)
    _, reading, exact, fuzzy = best
    match = "exact" if exact else "fuzzy" if fuzzy else "none"

    notes = []
    if len(exact) >= 2:  # both OCR reads agree on a tone the dictionary doesn't give
        reading = list(reading)
        for i, (ch, (b, t)) in enumerate(zip(hanzi, reading)):
            seen = {a[i][0] for _, a in exact}
            s = seen.pop() if len(seen) == 1 else 0
            # macron/caron (1/3) are routinely confused by the OCR; ignore those
            if not s or s == t or {s, t} == {1, 3}:
                continue
            valid = {tt for cand in candidates(ch) for bb, tt in cand if bb == b}
            if s in valid:   # a real reading of this character: trust the book (值得 zhídé)
                reading[i] = (b, s)
                notes.append(f"{ch}: using the book's tone {s} (dictionary says {t or 'neutral'})")
            else:
                notes.append(f"{ch}: OCR suggests tone {s}, kept dictionary tone {t or 'neutral'}")

    # word breaks: from the book's pinyin when it lines up, else dictionary words
    n = len(reading)
    aligned = [a for _, a in exact + fuzzy if all(s is not None for _, s, _ in a)]
    aligned_reads = [r for r, a in exact + fuzzy if all(s is not None for _, s, _ in a)]
    if aligned:
        spaces = []
        for i in range(1, n):
            votes = [bool(re.search(r"\s", r[a[i - 1][2]:a[i][1]])) and a[i][0] != -1
                     for r, a in zip(aligned_reads, aligned)]
            spaces.append(all(votes[:2]))
    else:
        bounds, k = set(), 0
        for w in words:
            k += len(w)
            bounds.add(k)
        spaces = [i in bounds for i in range(1, n)]

    # lay the syllables over the characters, keeping punctuation like （）……/
    syls = [add_tone(b, t) for b, t in reading]
    out, i, prev_syl = "", 0, False
    for c in chars:
        if CJK.match(c):
            s = syls[i]
            if prev_syl and i:
                if spaces[i - 1]:
                    out += " "
                elif split_tone(s[:1])[0].lower() in ("a", "e", "o"):
                    out += "'"
            out += s
            i += 1
            prev_syl = True
        else:
            p = {"（": " (", "(": " (", "）": ") ", ")": ") ", "、": "/"}.get(c, c)
            out += p
            prev_syl = False
    text = re.sub(r"\s+", " ", out).strip()
    if proper:
        text = " ".join(w[:1].upper() + w[1:] for w in text.split(" "))
    return Resolved(text, match, notes)


def to_pinyin(text: str) -> str:
    """Pinyin for arbitrary Chinese text (titles, labels): dictionary words, spaced."""
    parts = []
    for run in re.findall(r"[㐀-鿿]+", text):
        parts.append(resolve_pinyin(run, []).pinyin)
    return " ".join(parts)


def annotate(text: str) -> str:
    """Add pinyin after any Chinese inside an English string: 'the 的 phrase' -> 'the 的 (de) phrase'."""
    return re.sub(r"[㐀-鿿][㐀-鿿…（）]*", lambda m: f"{m.group(0)} ({to_pinyin(m.group(0))})", text)


def fix_chars_from_pinyin(chars: str, ocr_pinyin: str) -> str | None:
    """Find a dictionary word whose pinyin matches the OCR letters and that
    shares at least half its characters with the (mis)read OCR characters."""
    hanzi = "".join(c for c in chars if CJK.match(c))
    letters = "".join(l for _, l in letters_of(normalize_ocr_pinyin(ocr_pinyin))).replace("ü", "u")
    if len(hanzi) < 2:
        return None
    best = None
    for w in CEDICT_BY_LETTERS.get(letters, []):
        if len(w) != len(hanzi):
            continue
        same = sum(a == b for a, b in zip(w, hanzi))
        if same * 2 >= len(w) and (best is None or same > best[0]):
            best = (same, w)
    return chars.replace(hanzi, best[1]) if best else None


# ========================================================================= main


@dataclass
class Entry:
    book: str
    unit: int
    unit_title: str
    unit_title_zh: str
    unit_title_pinyin: str
    num: str
    chars: str
    pinyin: str
    pos: str
    meaning: str
    section: str
    page: int
    review: list[str] = field(default_factory=list)

    @property
    def pos_parts(self) -> list[str]:
        return [p for p in re.split(r"[/、]", self.pos) if p]

    @property
    def pos_pinyin(self) -> str:
        return "/".join(POS_INFO.get(p, (to_pinyin(p), ""))[0] for p in self.pos_parts)

    @property
    def pos_en(self) -> str:
        return "/".join(POS_INFO.get(p, ("", p))[1] for p in self.pos_parts)

    @property
    def flagged(self) -> bool:
        return any("disagree" in n or "using the book's tone" in n or "no characters" in n for n in self.review)


def unit_titles(book: str) -> dict[int, tuple[str, str]]:
    txt = (OUT_ROOT / book / f"{book}.txt").read_text(encoding="utf-8")
    titles = {}
    for m in re.finditer(r"第.{1,2}单元\s+(\S+)\s+Unit (\d+)\s+(.+?)(?:\s+\d+)?$", txt, re.M):
        titles.setdefault(int(m.group(2)), (m.group(1), m.group(3).strip()))
    return titles


def clean_chars(s: str) -> str:
    s = s.replace("(", "（").replace(")", "）").replace("...", "……").replace("⋯", "…").replace("•", "…")
    s = re.sub(r"…+", "……", s)
    return re.sub(r"\s+", "", s)


def clean_meaning(s: str) -> str:
    s = s.translate(ripper.FULLWIDTH_IN_LATIN).replace("•", ".").replace("⋯", "...").replace("…", "...")
    s = re.sub(r"\.{2,}", "...", s)
    s = re.sub(r"^[=•·\-\s]+", "", s)
    if re.fullmatch(r"[A-Z]{2,3}", s) and s not in ("OK", "TV", "PC", "CD", "DVD"):
        s = s.lower()  # small caps read as capitals ("SO" -> "so")
    return re.sub(r"\s+", " ", s).strip()


def load_overrides() -> dict:
    ov = defaultdict(dict)
    if OVERRIDES.exists():
        for r in csv.DictReader(OVERRIDES.open(encoding="utf-8")):
            ov[(r["book"], int(r["unit"]), r.get("section") or "main", r["no"])][r["field"]] = r["value"]
    return ov


def build(book: str, overrides: dict) -> list[Entry]:
    titles = unit_titles(book)
    gloss = defaultdict(list)
    for g in glossary_rows(book):
        gloss[clean_chars(g.chars)].append(g)

    entries = []
    for unit, start in enumerate(find_pages(book, r"VOCABULARY LIST"), 1):
        rows = extract_unit(book, start)
        prev = {"main": 0, "proper": 0}
        for r in rows:  # fill / repair row numbers from sequence
            if not r.num.isdigit() or int(r.num) != prev[r.section] + 1:
                r.num = str(prev[r.section] + 1)
            prev[r.section] = int(r.num)

        zh, en = titles.get(unit, ("", ""))
        for r in rows:
            proper = r.section == "proper"
            notes = []
            chars = clean_chars(r.chars)
            if not r.pinyin.strip():
                r.pinyin = reocr_cell(book, r, "pinyin")
            if not chars:
                chars = clean_chars(reocr_cell(book, r))

            def attempt(ch):
                g = ([x for x in gloss.get(ch, []) if x.unit == str(unit)] or gloss.get(ch, [])) if ch else []
                reads = [r.pinyin] + [x.pinyin for x in g[:1]]
                return resolve_pinyin(ch, reads, proper, clean_meaning(r.meaning)), g

            res, g = attempt(chars)
            if res.match != "exact":
                again = clean_chars(reocr_cell(book, r))
                if again and again != chars:
                    res2, g2 = attempt(again)
                    if res2.match == "exact" or (res2.match == "fuzzy" and res.match == "none"):
                        notes.append(f"characters re-read as {again} (first read {chars or '—'})")
                        chars, res, g = again, res2, g2
            if res.match == "none":
                fixed = fix_chars_from_pinyin(chars, r.pinyin)
                if fixed:
                    res2, g2 = attempt(fixed)
                    if res2.match == "exact":
                        notes.append(f"characters corrected from {chars} via pinyin")
                        chars, res, g = fixed, res2, g2
            if res.match == "none" and chars:
                notes.append(f"characters and pinyin disagree (OCR pinyin: {r.pinyin!r})")
            notes += res.notes

            if not r.pos and r.poscell:
                again = reocr_cell(book, r, "pos").replace("／", "/")
                if POS_RE.match(again):
                    r.pos = again
            pos = normalize_pos(r.pos.replace("，", "、").replace(",", "、"))
            if not pos and g and g[0].pos:
                pos = g[0].pos
            if proper:
                pos = pos or "专名"
            meaning = clean_meaning(r.meaning or (g[0].meaning if g else ""))
            if not meaning:
                notes.append("no meaning found")

            e = Entry(book, unit, en, zh, to_pinyin(zh), r.num, chars, res.pinyin, pos,
                      meaning, r.section, r.page, notes)
            for f, v in overrides.get((book, unit, r.section, r.num), {}).items():
                setattr(e, f, v)
                e.review = [n for n in e.review if "disagree" not in n and "tone" not in n]
                e.review.append(f"{f} set manually")
            entries.append(e)
    return entries


def write_outputs(all_entries: list[Entry]) -> None:
    VOCAB_DIR.mkdir(exist_ok=True)
    with open(VOCAB_DIR / "vocabulary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["book", "unit", "unit_title_zh", "unit_title_pinyin", "unit_title_en", "section",
                    "no", "character", "pinyin", "pos", "pos_pinyin", "pos_en", "meaning",
                    "pdf_page", "review"])
        for e in all_entries:
            w.writerow([e.book, e.unit, e.unit_title_zh, e.unit_title_pinyin, e.unit_title, e.section,
                        e.num, e.chars, e.pinyin, e.pos, e.pos_pinyin, e.pos_en, annotate(e.meaning),
                        e.page, "; ".join(e.review)])
    for book in dict.fromkeys(e.book for e in all_entries):
        lines = [f"# {book} — Vocabulary by Unit", "",
                 "⚠ = the OCR'd characters and pinyin disagreed; check against the book.", ""]
        for unit in sorted({e.unit for e in all_entries if e.book == book}):
            es = [e for e in all_entries if e.book == book and e.unit == unit]
            h = es[0]
            lines += [f"## Unit {unit}: {h.unit_title_zh} ({h.unit_title_pinyin}) — {h.unit_title}", ""]
            for section, label in (("main", None), ("proper", "专有名词 (zhuānyǒu míngcí) — Proper nouns")):
                group = [e for e in es if e.section == section]
                if not group:
                    continue
                if label:
                    lines += [f"### {label}", ""]
                lines += ["| # | Character | Pinyin | Part of speech | Meaning |",
                          "|---|---|---|---|---|"]
                for e in group:
                    pos = f"{e.pos} ({e.pos_pinyin}) {e.pos_en}" if e.pos else ""
                    flag = " ⚠" if e.flagged else ""
                    lines.append(f"| {e.num} | {e.chars} | {e.pinyin}{flag} | {pos} | {annotate(e.meaning)} |")
                lines.append("")
        (VOCAB_DIR / book).mkdir(parents=True, exist_ok=True)
        (VOCAB_DIR / book / "vocabulary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    load_cedict()
    overrides = load_overrides()
    books = sorted(p.name for p in OUT_ROOT.iterdir() if (p / "ocr").is_dir())
    all_entries = []
    for book in books:
        es = build(book, overrides)
        units = sorted({e.unit for e in es})
        print(f"{book}: {len(es)} words in {len(units)} units, {sum(e.flagged for e in es)} flagged for review")
        all_entries += es
    write_outputs(all_entries)
    print(f"-> {VOCAB_DIR}/vocabulary.csv, " + ", ".join(f"{VOCAB_DIR}/{b}/vocabulary.md" for b in books))


if __name__ == "__main__":
    main()
