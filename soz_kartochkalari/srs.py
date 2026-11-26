"""SM-2 takrorlash algoritmi va javoblarni solishtirish (interfeyssiz, test qilinadi).

SM-2 (P. Wozniak, 1987): sifat q = 0..5.
  q < 3  -> takrorlar soni 0 ga tushadi, interval 1 kun (karta qayta o'rganiladi);
  q >= 3 -> 1-takror: 1 kun, 2-takror: 6 kun, keyin interval * EF ("Yaxshi").
  Tugmalar farqli bo'lishi uchun: "Qiyin" interval * 1.2, "Oson" interval * EF * 1.3 (Anki uslubidagi kengaytma).
  EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)), EF >= 1.3.
Interfeysdagi 4 tugma: 1 Yana (q=1), 2 Qiyin (q=3), 3 Yaxshi (q=4), 4 Oson (q=5).
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List, Set, Tuple

GRADE_TO_Q = {1: 1, 2: 3, 3: 4, 4: 5}
MIN_EF = 1.3
START_EF = 2.5
MATURE_DAYS = 21


@dataclass
class CardState:
    reps: int = 0
    interval: int = 0
    ef: float = START_EF
    lapses: int = 0


def sm2(state: CardState, q: int) -> CardState:
    """Bitta takrordan keyingi yangi holat."""
    if not 0 <= q <= 5:
        raise ValueError("q must be 0..5")
    ef = state.ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ef = max(MIN_EF, round(ef, 4))
    if q < 3:
        return CardState(reps=0, interval=1, ef=ef, lapses=state.lapses + (1 if state.reps > 0 else 0))
    reps = state.reps + 1
    if reps == 1:
        interval = 4 if q == 5 else 1
    elif reps == 2:
        interval = {3: 4, 4: 6, 5: 8}[q]
    else:
        good = state.interval * state.ef
        if q == 3:                                   # Qiyin: sekinroq o'sish, lekin kamida +1 kun
            interval = max(state.interval + 1, _r(state.interval * 1.2))
        elif q == 5:                                 # Oson: qo'shimcha 30%
            interval = _r(good * 1.3)
        else:
            interval = _r(good)
    return CardState(reps=reps, interval=max(1, interval), ef=ef, lapses=state.lapses)


def _r(x: float) -> int:
    return int(x + 0.5)


def review(state: CardState, grade: int, today: date) -> Tuple[CardState, date]:
    """grade 1..4 (tugma) -> yangi holat va keyingi takror sanasi."""
    new = sm2(state, GRADE_TO_Q[grade])
    return new, today + timedelta(days=new.interval)


def preview_intervals(state: CardState) -> dict:
    """Har bir tugma uchun keyingi interval (kunlarda) — tugmalar ostida ko'rsatish uchun."""
    return {g: sm2(state, q).interval for g, q in GRADE_TO_Q.items()}


def card_category(reps: int, interval: int, seen: bool) -> str:
    """'new' | 'learning' | 'mature'."""
    if not seen:
        return "new"
    return "mature" if interval >= MATURE_DAYS and reps > 0 else "learning"


# --------------------------------------------------------------------------- javobni tekshirish
_APOS = "'`´ʻʼ‘’"


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().strip()
    for ch in _APOS:
        s = s.replace(ch, "'")
    s = re.sub(r"\([^)]*\)", " ", s)              # qavs ichidagi izohlar
    s = re.sub(r"[^\w\s'-]", " ", s)
    s = s.replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def variants(answer: str) -> List[str]:
    """'yo'l, usul; to'g'ri' -> ['yo'l', 'usul', 'to'g'ri']."""
    parts = re.split(r"[,;/]", answer or "")
    out = [normalize(p) for p in parts]
    out = [p for p in out if p]
    full = normalize(answer)
    if full and full not in out:
        out.append(full)
    return out


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def check_answer(given: str, expected: str) -> str:
    """'correct' | 'close' (1 ta harf xato, uzun so'zlarda 2) | 'wrong'."""
    g = normalize(given)
    if not g:
        return "wrong"
    best = None
    for v in variants(expected):
        d = levenshtein(g, v)
        best = d if best is None else min(best, d)
        if d == 0:
            return "correct"
    if best is not None:
        lim = 1 if len(g) <= 7 else 2
        if best <= lim:
            return "close"
    return "wrong"


# --------------------------------------------------------------------------- seriya (streak)
def streak(days_met: Set[date], today: date) -> int:
    """Kunlik maqsad bajarilgan ketma-ket kunlar. Bugun hali bajarilmagan bo'lsa, kechagidan sanaladi."""
    d = today if today in days_met else today - timedelta(days=1)
    n = 0
    while d in days_met:
        n += 1
        d -= timedelta(days=1)
    return n


def best_streak(days_met: Iterable[date]) -> int:
    best = cur = 0
    prev = None
    for d in sorted(set(days_met)):
        cur = cur + 1 if prev is not None and (d - prev).days == 1 else 1
        best = max(best, cur)
        prev = d
    return best
