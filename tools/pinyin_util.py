#!/usr/bin/env python3
"""Sentence-level pinyin in the style of the textbooks.

    from pinyin_util import sentence_pinyin, annotate_inline
    sentence_pinyin("你喜欢红的还是绿的？")   # -> "Nǐ xǐhuan hóng de háishi lǜ de?"
    annotate_inline('the verbs "有" and "是"')  # -> 'the verbs "有 (yǒu)" and "是 (shì)"'

Words come from CC-CEDICT (longest match), readings prefer the dictionary's
neutral-tone forms (东西 dōngxi, 喜欢 xǐhuan), grammatical particles are
neutral (的 了 吗 呢 吧 啊 着 们 个 里…), and 一/不 tone sandhi is applied
the way textbooks print it.

CLI:  .venv/bin/python pinyin_util.py "你喜欢红的还是绿的？"
"""
from __future__ import annotations

import re
import sys

from pypinyin import Style, pinyin

import paths
import vocab
from vocab import CEDICT_DB, add_tone, split_tone

_loaded = False


def _ensure():
    global _loaded
    if not _loaded:
        vocab.load_cedict()
        _loaded = True


HAN = re.compile(r"[㐀-鿿]")
PUNCT = {"，": ",", "。": ".", "？": "?", "！": "!", "：": ":", "；": ";", "、": ",",
         "“": "\"", "”": "\"", "‘": "'", "’": "'", "（": "(", "）": ")", "《": "\"", "》": "\"",
         "…": "…", "—": "—", "～": "~", "·": "·", "／": "/", "＋": "+"}
# characters that are neutral when they stand alone as grammatical words
NEUTRAL_SINGLE = {"的": "de", "了": "le", "吗": "ma", "呢": "ne", "吧": "ba", "啊": "a", "呀": "ya",
                  "着": "zhe", "们": "men", "么": "me", "地": "de", "得": "de", "过": "guo", "嘛": "ma",
                  "个": "ge", "里": "li", "子": "zi", "啦": "la"}
NEUTRAL_KEEP_TONE_AFTER = set("第")  # (unused hook for future rules)
# characters that keep a full tone even when alone (override NEUTRAL_SINGLE in context)
POTENTIAL_COMPLEMENTS = set("下了动完到懂见起出开去来住好清会")
# names from the New Target Chinese books (extend in names.txt: 汉字<TAB>Pinyin)
NAMES = {"大龙": "Dàlóng", "小丽": "Xiǎolì", "艾娜": "Àinà", "查理": "Chálǐ", "李伟": "Lǐ Wěi",
         "麦克": "Màikè", "王先生": "Wáng xiānsheng"}


def _load_names():
    try:
        with open(paths.NAMES, encoding="utf-8") as f:
            for line in f:
                if "\t" in line:
                    k, v = line.rstrip("\n").split("\t", 1)
                    NAMES[k] = v
    except FileNotFoundError:
        pass


_load_names()


GE_WORDS = {"个子", "个人", "个别", "个性", "个体", "个儿", "这个", "那个", "哪个", "整个", "各个"}
COMPLEMENT_WORDS = {"上去", "下去", "上来", "下来", "进去", "出去", "回去", "过去", "起来", "出来", "进来",
                    "回来", "过来", "完", "动", "到", "懂", "见", "了", "下", "开", "住", "着", "起", "清楚", "干净"}
DEGREE_WORDS = {"最好", "最后", "最近", "最初", "最终", "最多", "最少", "真是", "真正", "真的", "真心",
                "太太", "太阳", "太极", "更加", "更新", "很难说"}  # real words starting with 很/太/真/最/更
NUMERALS = set("一二两三四五六七八九十几每某半")  # 这个/那个 stay joined (zhège)


def _segment(run: str) -> list[str]:
    """jieba word segmentation, with textbook-style splits (三个 -> 三 个, 买点儿 -> 买 点儿)."""
    import logging
    import jieba
    jieba.setLogLevel(logging.WARNING)
    for name in list(NAMES) + EXTRA_WORDS:
        jieba.add_word(name)
    jieba.suggest_freq(("中文", "书"), True)
    out = []
    m = re.search(r"(.)\1(.)\2", run)
    if m and m.group(1) + m.group(2) in CEDICT_DB:
        return _segment(run[:m.start()]) + [m.group(0)] + _segment(run[m.end():])
    for w in jieba.cut(run, HMM=False):
        if len(w) >= 2 and w[-1] == "个" and all(c in NUMERALS for c in w[:-1]):
            out += [w[:-1], "个"]
        elif len(w) > 2 and w.endswith("点儿") and w not in ("差点儿", "一点儿", "有点儿"):
            out += [w[:-2], "点儿"]
        elif len(w) >= 2 and w[-1] == "里" and w not in ("这里", "那里", "哪里", "公里", "千里", "万里", "夜里", "心里"):
            out += [w[:-1], "里"]        # locative 里: 店里 -> diàn li
        elif len(w) == 2 and w[0] == "不" and w[1] in "是想能会要去来用在太":
            out += ["不", w[1]]          # textbooks write bú shì, bù xiǎng
        elif len(w) == 3 and w[1:] in ("起来", "上去", "下来", "出来") and w not in ("起起来",):
            out += [w[0], w[1:]]          # 看起来 kàn qǐlai
        elif len(w) == 2 and w[0] in "我你他她它" and w[1] in "会要想是在有能":
            out += [w[0], w[1]]           # 我会 wǒ huì
        elif len(w) == 3 and w[0] == w[1] and w[2] not in "的地":
            out += [w[:2], w[2]]          # 跑跑步 -> 跑跑 步 (pǎopao bù)
        elif len(w) == 3 and w[0] == w[2] and w[1] in "一不":
            out += [w[0], w[1], w[2]]     # 比一比 bǐ yi bǐ, 去不去 qù bu qù
        elif len(w) >= 3 and w[1] == "没" and w[0] == w[2]:
            out += [w[0], w[1:]]          # 有没有 yǒu méiyǒu
        elif len(w) >= 2 and w[0] in "很太真最更" and w not in DEGREE_WORDS \
                and (len(w) == 2 or w[1:] in CEDICT_DB):
            out += [w[0], w[1:]]          # 很漂亮 -> 很 漂亮 (hěn piàoliang), 很贵 -> hěn guì
        elif len(w) > 1 and "个" in w and w not in GE_WORDS and w[w.index("个"):w.index("个") + 2] not in GE_WORDS:
            i = w.index("个")              # 下个月 -> 下 个 月 (xià ge yuè)
            out += [x for x in (w[:i], "个", w[i + 1:]) if x]
        elif len(w) == 3 and w[1:] == "文书" and w[0] in "中英法日德俄":
            out += [w[:2], "书"]          # 英文书 -> 英文 书
        elif w.startswith("文") and out and out[-1] in ("中", "英", "法", "日", "德", "俄") and len(w) >= 2:
            out[-1] += "文"                # 中/文书 -> 中文 书
            out.append(w[1:])
        elif out and len(w) == 1 and out[-1] == w and w not in "的了吗呢吧啊":
            out[-1] = w + w               # 说/说 -> 说说 (reduplication)
        else:
            out.append(w)
    return out


DIRECTION_BIAN = {d + "边" for d in "东西南北上下里外前后左右"}  # 北边 běibian (neutral 边)
FIXED = {"谁": [("shei", 2)], "看来": [("kan", 4), ("lai", 2)], "起来": [("qi", 3), ("lai", 0)], "可不": [("ke", 3), ("bu", 4)], "来着": [("lai", 2), ("zhe", 0)],
         "恨不得": [("hen", 4), ("bu", 0), ("de", 0)], "怪不得": [("guai", 4), ("bu", 0), ("de", 0)],
         "不得了": [("bu", 4), ("de", 2), ("liao", 3)], "好处": [("hao", 3), ("chu", 4)],
         "坏处": [("huai", 4), ("chu", 4)]}
EXTRA_WORDS = ["来着", "恨不得", "怪不得", "达人", "分句", "复句", "差点儿"]  # words jieba should keep together
WEI2_AFTER = {"通常", "一般", "形式", "常", "多", "均", "即", "都", "也", "分别", "大多", "主要", "称", "视", "改"}  # textbook readings that differ from pypinyin's default


def _word_reading(w: str) -> list[tuple[str, int]]:
    if w in NAMES:
        return [(NAMES[w], -1)]  # pre-formatted
    if w in FIXED:
        return list(FIXED[w])
    if len(w) == 4 and w[0] == w[1] and w[2] == w[3] and w[0] + w[2] in CEDICT_DB:
        # AABB reduplication (漂漂亮亮): syllables of AB, second one with its full tone
        a, b = CEDICT_DB[w[0] + w[2]][0]
        if b[1] == 0:
            b = split_tone(pinyin(w[2], style=Style.TONE)[0][0])
        return [a, a, b, b]
    if w in DIRECTION_BIAN:
        first = split_tone(pinyin(w[0], style=Style.TONE)[0][0])
        return [first, ("bian", 0)]
    if w in vocab.CEDICT_PROPER and not w.startswith(("星期", "礼拜")) \
            and not (len(w) == 2 and w[0] == "周" and w[1] in "一二三四五六日末"):  # 中文 Zhōngwén, 北京 Běijīng
        r = CEDICT_DB[w][0]
        word = vocab.join_syllables([add_tone(b, t) for b, t in r])
        return [(word[0].upper() + word[1:], -1)]
    entries = [e for e in CEDICT_DB.get(w, [])]
    default = [split_tone(p[0]) for p in pinyin(w, style=Style.TONE)]
    if len(w) > 1 and entries:
        # Pick the dictionary entry that agrees with pypinyin's (frequency-based) reading,
        # allowing neutral tones where the textbook-style entry has them:
        # 结果 jiéguǒ (not jiēguǒ), 东西 dōngxi "thing", 地方 dìfang.
        agree = [e for e in entries if len(e) == len(default)
                 and all(b == db and (t == dt or t == 0) for (b, t), (db, dt) in zip(e, default))]
        if agree:
            return max(agree, key=lambda e: sum(t == 0 for _, t in e))
        return entries[0]
    return default


def _sandhi(tokens: list[tuple[str, list]]):
    """Apply 一/不 sandhi across the flattened syllable list (in place)."""
    flat = []  # (token index, syllable index, char)
    for ti, (w, syls) in enumerate(tokens):
        if not syls or syls[0][1] == -1 or len(syls) != len(w):
            flat.append((ti, -1, ""))   # punctuation / names / 儿化 words break the chain
            continue
        for si, ch in enumerate(w):
            flat.append((ti, si, ch))
    for k, (ti, si, ch) in enumerate(flat):
        if ch not in ("一", "不") or k + 1 >= len(flat) or flat[k + 1][1] < 0:
            continue
        nti, nsi, nch = flat[k + 1]
        nxt = 4 if nch == "个" else tokens[nti][1][nsi][1]   # 个 is underlyingly gè
        prev = flat[k - 1][2] if k else ""
        word = tokens[ti][0]
        if word in FIXED:
            continue
        if ch == "一":
            if prev and prev == nch:
                tokens[ti][1][si] = ("yi", 0)   # A一A: 看一看 kàn yi kàn
                continue
            if prev == "第" or nch in "月号日" or re.match(r"[零一二三四五六七八九十百千万]", nch):
                continue
            tokens[ti][1][si] = ("yi", 2 if nxt == 4 else 4)
        elif prev and prev == nch:
            tokens[ti][1][si] = ("bu", 0)   # A不A question: 高不高 gāo bu gāo
        elif word == "不" and tokens[nti][0] in COMPLEMENT_WORDS and ti and len(tokens[ti - 1][0]) == 1 \
                and HAN.match(tokens[ti - 1][0]) and tokens[ti - 1][0] not in "我你他她它您谁也都还就才又很太真最更":
            tokens[ti][1][si] = ("bu", 0)   # potential complement: 爬不上去 pá bu shàngqu
        elif si == 0 and len(word) >= 2 and (word[1:] in COMPLEMENT_WORDS or word[1:] in POTENTIAL_COMPLEMENTS) \
                and ti and HAN.match(tokens[ti - 1][0][-1:] or " ") and len(tokens[ti - 1][0]) == 1 \
                and tokens[ti - 1][0] not in "我你他她它您谁也都还就才又很太真最更":
            tokens[ti][1][si] = ("bu", 0)   # 找 + 不到 -> zhǎo bu dào
        elif nch == "住":
            tokens[ti][1][si] = ("bu", 0)   # ……不住 bu zhù
        else:
            # potential complement inside one word: 吃不下, 走不动, 了不起 -> neutral bu
            if si >= 1 and (word[si + 1:] in COMPLEMENT_WORDS
                            or (len(word) == si + 2 and word[si + 1] in POTENTIAL_COMPLEMENTS | set("起"))):
                tokens[ti][1][si] = ("bu", 0)
            elif nxt == 4:
                tokens[ti][1][si] = ("bu", 2)
            else:
                tokens[ti][1][si] = ("bu", 4)


def sentence_pinyin(text: str, capitalize: bool = True) -> str:
    _ensure()
    tokens: list[tuple[str, list]] = []
    for piece in re.findall(r"[㐀-鿿]+|[^㐀-鿿]", text):
        if HAN.match(piece):
            for w in _segment(piece):
                if len(w) == 1 and w in NEUTRAL_SINGLE:
                    syls = [(NEUTRAL_SINGLE[w], 0)]
                    # 子/里/个 keep their tone when not following another character
                    if w in "子里个" and (not tokens or not HAN.match(tokens[-1][0][-1:])):
                        syls = _word_reading(w)
                elif w == "为" and tokens and tokens[-1][0] in WEI2_AFTER:
                    syls = [("wei", 2)]   # 为 = "is / as" after 通常, 形式 …: wéi
                else:
                    syls = [(s[0], s[1]) for s in _word_reading(w)]
                tokens.append((w, list(syls)))
        else:
            tokens.append((piece, []))
    _sandhi(tokens)
    for k, (w, syls) in enumerate(tokens):
        nxt = tokens[k + 1][0] if k + 1 < len(tokens) else ""
        if len(w) == 2 and w[0] == w[1] and len(syls) == 2 and syls[0][1] != -1 \
                and nxt not in ("的", "地") and w not in CEDICT_DB:
            syls[1] = (syls[1][0], 0)   # 看看 kànkan, 听听 tīngting

    out, in_quote = "", False
    for w, syls in tokens:
        if not syls:  # punctuation / latin / digits
            p = PUNCT.get(w, w)
            if p == '"':
                out = out.rstrip() + ('" ' if in_quote else ' "')
                in_quote = not in_quote
            elif p in ",.?!:;":
                out = out.rstrip() + p + " "
            elif p == ")":
                out = out.rstrip() + ") "
            elif p == "(":
                out = out.rstrip() + " ("
            elif p.isspace():
                out += " "
            elif p == "/":
                out = out.rstrip() + "/"
            elif p == "…":
                out = out.rstrip() + p
            else:
                out += p
            continue
        if w == "儿" and out and out[-1].isalpha():
            out += "r"                  # 画画儿 huà huàr
            continue
        if syls[0][1] == -1:
            word = syls[0][0]
        else:
            word = vocab.join_syllables([add_tone(b, t) for b, t in syls])
        if out and not out.endswith((" ", "(", '"', "…", "—", "+", "/")):
            out += " "
        out += word
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r'^" ', '"', out)
    out = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", out)  # Tā 50 suì
    out = re.sub(r"(?<=[a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü])(?=[A-Z])", " ", out)  # bùrú B, kǎlā OK
    if capitalize and out:
        def cap_first(t):
            for k, c in enumerate(t):
                if c.isalpha():
                    return t[:k] + c.upper() + t[k + 1:]
            return t
        out = cap_first(out)
        out = re.sub(r"(?<=[.?!] )(\S+)", lambda m: cap_first(m.group(1)), out)
        # after a colon only when it follows a short speaker label (A:, Lǐ Wěi:)
        out = re.sub(r"((?:^|[.?!] )(?:\S+ ){0,2}\S+: )(\S+)", lambda m: m.group(1) + cap_first(m.group(2)), out)
    return out


def annotate_inline(text: str) -> str:
    """Add (pinyin) after each run of Chinese inside mostly-English text."""
    def rep(m):
        zh = m.group(0)
        return f"{zh} ({sentence_pinyin(zh, capitalize=False).strip(' .,')})"
    return re.sub(r"[\u3400-\u9fff]+(?:…+[\u3400-\u9fff]+)*…*", rep, text)


if __name__ == "__main__":
    for arg in sys.argv[1:] or [line.rstrip("\n") for line in sys.stdin]:
        print(sentence_pinyin(arg))


# ---------------------------------------------------------------- ruby (interlinear)
import unicodedata  # noqa: E402

_SYLLABLES: set = set()


def _syllables() -> set:
    """All toneless pinyin syllables known to CC-CEDICT."""
    if not _SYLLABLES:
        _ensure()
        for entries in CEDICT_DB.values():
            for reading in entries:
                for b, _ in reading:
                    if b.isalpha() and b.islower():
                        _SYLLABLES.add(b)
        _SYLLABLES.update({"r", "ng", "m", "n", "ê"})
    return _SYLLABLES


def _toneless(s: str) -> str:
    out = [ch for ch in unicodedata.normalize("NFD", s.lower()) if ch not in "̄́̌̀"]
    return unicodedata.normalize("NFC", "".join(out))


def _split_word(word: str):
    """Split one pinyin word ('shǒujī', "Xī'ān", 'nǎr') into syllables, keeping tone marks."""
    syl = _syllables()
    out = []
    for part in re.split(r"['’\-]", word):
        if not part:
            continue
        part = unicodedata.normalize("NFC", part)
        flat = _toneless(part)
        if len(flat) != len(part):
            return None
        n = len(flat)
        dp = [None] * (n + 1)   # fewest syllables covering flat[:i]
        dp[0] = []
        for i in range(n):
            if dp[i] is None:
                continue
            for j in range(min(n, i + 6), i, -1):
                if flat[i:j] in syl and (dp[j] is None or len(dp[j]) > len(dp[i]) + 1):
                    dp[j] = dp[i] + [(i, j)]
        if dp[n] is None:
            return None
        out += [part[i:j] for i, j in dp[n]]
    return out


NUM_SYLLABLES = {"yi", "er", "san", "si", "wu", "liu", "qi", "ba", "jiu", "shi", "bai", "qian", "wan",
                 "ling", "dian", "liang", "fen", "zhi", "li", "mi"}


def ruby_segments(zh: str, py: str):
    """Align pinyin words to the characters they belong to.

    Each Han character takes one syllable (儿 after an -r syllable takes none); a run of digits
    takes the number syllables the pinyin spells out (60% -> bǎi fēn zhī liùshí); Latin words in
    the Chinese (a., OK, “Shūyíng”) are matched against themselves. Returns
    [(text, pinyin_or_None), ...] or None if the two can't be aligned.
    """
    import sys
    words = re.findall(r"[A-Za-z\u00C0-\u024F\u00FC\u00DC'\u2019\-]+", py)
    sylls, word_text = [], []
    for w in words:
        w = w.strip("-'\u2019")
        if not w or re.fullmatch(r"[A-Z]+", w):          # A, B, OK, AABB … are not pinyin
            continue
        parts = _split_word(w)
        if parts is None:
            return None
        wid = len(word_text)
        word_text.append(w)
        sylls += [(p, wid) for p in parts]

    units = re.findall(r"[\u3400-\u9fff]|[0-9.%]+|[A-Za-z\u00C0-\u024F\u00FC\u00DC]+|.", zh, re.S)
    n_units, n_syl = len(units), len(sylls)
    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))
    memo = {}

    def solve(i, k, prev_r):
        """Alignment of units[i:] with sylls[k:] -> list of (unit_text, kind, payload) or None."""
        key = (i, k, prev_r)
        if key in memo:
            return memo[key]
        if i == n_units:
            res = [] if k == n_syl else None
            memo[key] = res
            return res
        u = units[i]
        res = None
        if HAN.match(u):
            if u == "儿" and prev_r:
                rest = solve(i + 1, k, False)
                res = None if rest is None else [(u, "erhua", None)] + rest
            if res is None and k < n_syl:
                base = _toneless(sylls[k][0])
                r_flag = base.endswith("r") and base != "er" and len(base) > 1
                rest = solve(i + 1, k + 1, r_flag)
                if rest is not None:
                    res = [(u, "han", sylls[k][1])] + rest
        elif re.fullmatch(r"[0-9.%]+", u):
            m = 0
            while k + m < n_syl and _toneless(sylls[k + m][0]) in NUM_SYLLABLES:
                m += 1
            for take in range(m, -1, -1):               # longest first, back off if needed
                rest = solve(i + 1, k + take, False)
                if rest is not None:
                    res = [(u, "num", [s for s, _ in sylls[k:k + take]])] + rest
                    break
        elif re.fullmatch(r"[A-Za-z\u00C0-\u024F\u00FC\u00DC]+", u) and not u.isupper():
            parts = _split_word(u) or []
            j = len(parts)
            if parts and k + j <= n_syl and all(_toneless(a) == _toneless(b) for a, (b, _) in zip(parts, sylls[k:k + j])):
                rest = solve(i + 1, k + j, False)
                if rest is not None:
                    res = [(u, "plain", None)] + rest
            if res is None:
                rest = solve(i + 1, k, False)
                res = None if rest is None else [(u, "plain", None)] + rest
        else:
            if u in "～~" and k < n_syl and _toneless(sylls[k][0]) == "dao":   # 2号～4号 read “dào”
                rest = solve(i + 1, k + 1, False)
                if rest is not None:
                    res = [(u, "num", [sylls[k][0]])] + rest
            if res is None:
                rest = solve(i + 1, k, False)
                res = None if rest is None else [(u, "plain", None)] + rest
        memo[key] = res
        return res

    aligned = solve(0, 0, False)
    if aligned is None:
        return None
    out = []                                            # (text, pinyin, group key)
    last_wid = None
    for text, kind, payload in aligned:
        if kind == "han":
            if out and last_wid == payload and out[-1][2] == ("w", payload):
                out[-1] = (out[-1][0] + text, out[-1][1], out[-1][2])
            else:
                out.append((text, word_text[payload], ("w", payload)))
            last_wid = payload
        elif kind == "erhua":
            out[-1] = (out[-1][0] + text, out[-1][1], out[-1][2])
        elif kind == "num" and payload:
            out.append((text, " ".join(payload), ("n", len(out))))
            last_wid = None
        else:
            if out and out[-1][1] is None:
                out[-1] = (out[-1][0] + text, None, None)
            else:
                out.append((text, None, None))
            last_wid = None
    return [(t, p) for t, p, _ in out]


def ruby_html(zh: str, py: str = None):
    """HTML <ruby> markup with each word's pinyin attached (None if alignment fails)."""
    import html
    py = py or sentence_pinyin(zh)
    segs = ruby_segments(zh, py)
    if segs is None:
        return None
    esc = lambda x: html.escape(x, quote=False)
    return "".join(f"<ruby>{esc(t)}<rt>{esc(p)}</rt></ruby>" if p else esc(t) for t, p in segs)
