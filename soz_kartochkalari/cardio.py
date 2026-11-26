"""Import / eksport (CSV, Excel, TSV) va o'rnatilgan to'plamlar."""
import csv
import io
from pathlib import Path
from typing import Dict, List, Sequence

from .db import FIELDS

BUILTIN_DECKS = {
    "common300": {"file": "common300.txt", "name": {"uz": "300 ta eng ko'p ishlatiladigan so'z",
                                                    "ru": "300 самых употребительных слов",
                                                    "en": "300 most common words"}},
    "ielts150": {"file": "ielts150.txt", "name": {"uz": "IELTS Academic: boshlang'ich 150 so'z",
                                                  "ru": "IELTS Academic: базовые 150 слов",
                                                  "en": "IELTS Academic: starter 150 words"}},
    "graphics100": {"file": "graphics100.txt", "name": {"uz": "Kompyuter grafikasi terminlari (100)",
                                                        "ru": "Термины компьютерной графики (100)",
                                                        "en": "Computer graphics terms (100)"}},
}


def parse_builtin(text: str) -> List[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != 5:
            raise ValueError(f"bad line: {line[:40]}")
        out.append(dict(zip(FIELDS, (p.strip() for p in parts))))
    return out


def load_builtin(folder: Path, key: str) -> List[dict]:
    return parse_builtin((Path(folder) / BUILTIN_DECKS[key]["file"]).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- o'qish
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_table(path: str) -> List[List[str]]:
    """Faylni qatorlar ro'yxatiga o'qiydi: .xlsx, .csv, .tsv/.txt (Anki eksporti ham)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(p, read_only=True, data_only=True)
        ws = wb.active
        rows = [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        text = _decode(p.read_bytes())
        lines = [l for l in text.splitlines() if not l.startswith("#")]     # Anki: #separator:tab
        text = "\n".join(lines)
        if ext in (".tsv", ".txt") or "\t" in text.split("\n", 1)[0]:
            delim = "\t"
        else:
            try:
                delim = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|").delimiter
            except csv.Error:
                delim = ","
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
    return [r for r in rows if any(c for c in r)]


def guess_mapping(rows: List[List[str]]) -> Dict[int, str]:
    """Birinchi qator sarlavha bo'lsa — nomlariga qarab, aks holda tartib bo'yicha: so'z, tarjima..."""
    if not rows:
        return {}
    head = [c.lower() for c in rows[0]]
    names = {
        "word": ("word", "english", "so'z", "front", "слово", "term", "en"),
        "ipa": ("ipa", "transcription", "transkripsiya", "транскрипция", "pronunciation"),
        "uz": ("uz", "uzbek", "o'zbekcha", "tarjima", "back", "translation", "узбекский"),
        "ru": ("ru", "russian", "ruscha", "русский", "перевод"),
        "example": ("example", "misol", "пример", "sentence"),
    }
    m = {}
    for i, h in enumerate(head):
        for f, keys in names.items():
            if f not in m.values() and any(h == k or h.startswith(k) for k in keys):
                m[i] = f
                break
    if len(m) >= 2 and "word" in m.values():
        return m
    width = max(len(r) for r in rows)
    order = ["word", "uz", "ru", "example", "ipa"] if width <= 4 else ["word", "ipa", "uz", "ru", "example"]
    return {i: order[i] for i in range(min(width, len(order)))}


def has_header(rows: List[List[str]]) -> bool:
    if not rows:
        return False
    head = " ".join(c.lower() for c in rows[0])
    return any(k in head for k in ("word", "english", "so'z", "слово", "uz", "translation", "tarjima", "front"))


def apply_mapping(rows: List[List[str]], mapping: Dict[int, str], skip_header: bool) -> List[dict]:
    out = []
    for r in rows[1 if skip_header else 0:]:
        d = {f: "" for f in FIELDS}
        for i, f in mapping.items():
            if f and i < len(r):
                d[f] = r[i]
        if d["word"].strip():
            out.append(d)
    return out


# --------------------------------------------------------------------------- yozish
def export_rows(cards: Sequence) -> List[List[str]]:
    return [[c["word"], c["ipa"], c["uz"], c["ru"], c["example"]] for c in cards]


def write_csv(path: str, headers: Sequence[str], rows: Sequence[Sequence[str]], delimiter: str = ";"):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=delimiter)
        if headers:
            w.writerow(headers)
        w.writerows(rows)


def write_tsv(path: str, rows: Sequence[Sequence[str]]):
    """Anki bilan mos: sarlavhasiz, tab bilan ajratilgan, UTF-8."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("#separator:tab\n#html:false\n")
        for r in rows:
            f.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in r) + "\n")
