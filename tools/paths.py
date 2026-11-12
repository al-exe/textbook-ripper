"""Project paths, resolved from this file so the tools work from any directory.

    textbooks/            source PDFs                      (top level)
    study/                generated study materials        (top level)
    pdf/                  PDF versions of study/ for the iPad (top level)
    tools/                code + everything that supports it
      cache/<Book>/       OCR cache, full text, cell re-reads
      specs/<Book>/       hand-written study-material specs (JSON)
      data/               CC-CEDICT dictionary
      names.txt           character names for pinyin
      vocab_overrides.csv manual vocabulary fixes
"""
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
TEXTBOOKS = ROOT / "textbooks"
STUDY = ROOT / "study"
PDF = ROOT / "pdf"          # PDF versions of study/, same folder layout
CACHE = TOOLS / "cache"
SPECS = TOOLS / "specs"
DATA = TOOLS / "data"
CEDICT = DATA / "cedict_ts.u8"
NAMES = TOOLS / "names.txt"
OVERRIDES = TOOLS / "vocab_overrides.csv"
