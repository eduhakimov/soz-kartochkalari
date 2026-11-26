"""SQLite: to'plamlar, kartalar, takrorlash jurnali; navbat va statistika."""
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import srs

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    builtin TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    word TEXT NOT NULL,
    ipa TEXT DEFAULT '',
    uz TEXT DEFAULT '',
    ru TEXT DEFAULT '',
    example TEXT DEFAULT '',
    image TEXT DEFAULT '',
    reps INTEGER DEFAULT 0,
    interval INTEGER DEFAULT 0,
    ef REAL DEFAULT 2.5,
    lapses INTEGER DEFAULT 0,
    due TEXT,
    seen INTEGER DEFAULT 0,
    created TEXT
);
CREATE INDEX IF NOT EXISTS ix_cards_deck ON cards(deck_id);
CREATE INDEX IF NOT EXISTS ix_cards_due ON cards(due);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    grade INTEGER NOT NULL,
    mode TEXT DEFAULT 'flip',
    was_new INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_reviews_day ON reviews(day);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

FIELDS = ["word", "ipa", "uz", "ru", "example"]


class DB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self):
        self.con.close()

    def get_meta(self, k, default=None):
        r = self.con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set_meta(self, k, v):
        self.con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (k, str(v)))
        self.con.commit()

    # ------------------------------------------------------------------ to'plamlar
    def add_deck(self, name: str, builtin: str = None) -> int:
        cur = self.con.execute("INSERT INTO decks(name, builtin, created) VALUES(?,?,?)",
                               (name, builtin, datetime.now().isoformat(timespec="seconds")))
        self.con.commit()
        return cur.lastrowid

    def rename_deck(self, did: int, name: str):
        self.con.execute("UPDATE decks SET name=? WHERE id=?", (name, did))
        self.con.commit()

    def delete_deck(self, did: int):
        self.con.execute("DELETE FROM decks WHERE id=?", (did,))
        self.con.commit()

    def decks(self) -> List[sqlite3.Row]:
        return self.con.execute("SELECT * FROM decks ORDER BY id").fetchall()

    def deck(self, did: int):
        return self.con.execute("SELECT * FROM decks WHERE id=?", (did,)).fetchone()

    def deck_by_builtin(self, key: str):
        return self.con.execute("SELECT * FROM decks WHERE builtin=?", (key,)).fetchone()

    def deck_counts(self, did: int, today: date) -> Dict[str, int]:
        t = today.isoformat()
        r = self.con.execute(
            "SELECT COUNT(*) AS total, SUM(seen=0) AS new, SUM(seen=1 AND due<=?) AS due, "
            "SUM(seen=1 AND interval>=?) AS mature FROM cards WHERE deck_id=?",
            (t, srs.MATURE_DAYS, did)).fetchone()
        return {k: int(r[k] or 0) for k in ("total", "new", "due", "mature")}

    # ------------------------------------------------------------------ kartalar
    def add_card(self, did: int, word: str, ipa="", uz="", ru="", example="", image="") -> int:
        cur = self.con.execute(
            "INSERT INTO cards(deck_id, word, ipa, uz, ru, example, image, created) VALUES(?,?,?,?,?,?,?,?)",
            (did, word.strip(), ipa.strip(), uz.strip(), ru.strip(), example.strip(), image,
             datetime.now().isoformat(timespec="seconds")))
        self.con.commit()
        return cur.lastrowid

    def add_cards(self, did: int, rows: List[dict], skip_duplicates: bool = True) -> int:
        have = {r["word"].lower() for r in self.con.execute("SELECT word FROM cards WHERE deck_id=?", (did,))}
        n = 0
        now = datetime.now().isoformat(timespec="seconds")
        for r in rows:
            w = (r.get("word") or "").strip()
            if not w or (skip_duplicates and w.lower() in have):
                continue
            self.con.execute(
                "INSERT INTO cards(deck_id, word, ipa, uz, ru, example, created) VALUES(?,?,?,?,?,?,?)",
                (did, w, (r.get("ipa") or "").strip(), (r.get("uz") or "").strip(), (r.get("ru") or "").strip(),
                 (r.get("example") or "").strip(), now))
            have.add(w.lower())
            n += 1
        self.con.commit()
        return n

    def update_card(self, cid: int, **kw):
        allowed = set(FIELDS) | {"image", "deck_id"}
        sets = {k: v for k, v in kw.items() if k in allowed}
        if not sets:
            return
        q = ", ".join(f"{k}=?" for k in sets)
        self.con.execute(f"UPDATE cards SET {q} WHERE id=?", (*sets.values(), cid))
        self.con.commit()

    def delete_card(self, cid: int):
        self.con.execute("DELETE FROM cards WHERE id=?", (cid,))
        self.con.commit()

    def card(self, cid: int):
        return self.con.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()

    def cards(self, did: Optional[int] = None, search: str = "") -> List[sqlite3.Row]:
        q = "SELECT cards.*, decks.name AS deck_name FROM cards JOIN decks ON decks.id=cards.deck_id WHERE 1=1"
        args = []
        if did:
            q += " AND deck_id=?"
            args.append(did)
        if search:
            q += " AND (word LIKE ? OR uz LIKE ? OR ru LIKE ? OR example LIKE ?)"
            s = f"%{search}%"
            args += [s, s, s, s]
        q += " ORDER BY cards.id"
        return self.con.execute(q, args).fetchall()

    def reset_card(self, cid: int):
        self.con.execute("UPDATE cards SET reps=0, interval=0, ef=2.5, lapses=0, due=NULL, seen=0 WHERE id=?", (cid,))
        self.con.commit()

    # ------------------------------------------------------------------ navbat
    def new_today(self, today: date) -> int:
        return self.con.execute("SELECT COUNT(*) FROM reviews WHERE day=? AND was_new=1",
                                (today.isoformat(),)).fetchone()[0]

    def queue(self, did: Optional[int], today: date, new_limit: int, review_limit: int = 500,
              shuffle_seed: int = None) -> List[sqlite3.Row]:
        """Bugungi navbat: muddati kelgan takrorlar (eng eskisi oldin) + kunlik limitgacha yangi kartalar."""
        where = "deck_id=?" if did else "1=1"
        args = [did] if did else []
        due = self.con.execute(
            f"SELECT * FROM cards WHERE {where} AND seen=1 AND due<=? ORDER BY due, id LIMIT ?",
            (*args, today.isoformat(), review_limit)).fetchall()
        left = max(0, new_limit - self.new_today(today))
        new = self.con.execute(f"SELECT * FROM cards WHERE {where} AND seen=0 ORDER BY id LIMIT ?",
                               (*args, left)).fetchall()
        items = list(due) + list(new)
        if shuffle_seed is not None:
            random.Random(shuffle_seed).shuffle(items)
        return items

    def answer(self, cid: int, grade: int, mode: str = "flip", today: date = None, now: datetime = None):
        """Kartaga baho qo'yadi: SM-2 hisoblanadi, jurnalga yoziladi. Yangi holatni qaytaradi."""
        today = today or date.today()
        now = now or datetime.now()
        c = self.card(cid)
        st = srs.CardState(c["reps"], c["interval"], c["ef"], c["lapses"])
        new, due = srs.review(st, grade, today)
        self.con.execute("UPDATE cards SET reps=?, interval=?, ef=?, lapses=?, due=?, seen=1 WHERE id=?",
                         (new.reps, new.interval, new.ef, new.lapses, due.isoformat(), cid))
        self.con.execute("INSERT INTO reviews(card_id, ts, day, grade, mode, was_new) VALUES(?,?,?,?,?,?)",
                         (cid, now.isoformat(timespec="seconds"), today.isoformat(), grade, mode,
                          0 if c["seen"] else 1))
        self.con.commit()
        return new, due

    # ------------------------------------------------------------------ statistika
    def reviews_per_day(self, start: date, end: date) -> Dict[date, int]:
        rows = self.con.execute("SELECT day, COUNT(*) AS n FROM reviews WHERE day BETWEEN ? AND ? GROUP BY day",
                                (start.isoformat(), end.isoformat())).fetchall()
        return {date.fromisoformat(r["day"]): r["n"] for r in rows}

    def days_meeting_goal(self, goal: int) -> set:
        rows = self.con.execute("SELECT day FROM reviews GROUP BY day HAVING COUNT(*) >= ?", (max(1, goal),))
        return {date.fromisoformat(r["day"]) for r in rows}

    def accuracy(self, start: date) -> Optional[float]:
        r = self.con.execute("SELECT COUNT(*) AS n, SUM(grade>1) AS ok FROM reviews WHERE day>=?",
                             (start.isoformat(),)).fetchone()
        return (r["ok"] or 0) / r["n"] if r["n"] else None

    def categories(self) -> Dict[str, int]:
        out = {"new": 0, "learning": 0, "mature": 0}
        for r in self.con.execute("SELECT reps, interval, seen FROM cards"):
            out[srs.card_category(r["reps"], r["interval"], bool(r["seen"]))] += 1
        return out

    def forecast(self, today: date, days: int = 7) -> List[int]:
        """Keyingi kunlarda muddati keladigan kartalar soni (bugungi kun ichida o'tib ketganlari ham)."""
        out = []
        for i in range(days):
            d = today + timedelta(days=i)
            if i == 0:
                n = self.con.execute("SELECT COUNT(*) FROM cards WHERE seen=1 AND due<=?", (d.isoformat(),)).fetchone()[0]
            else:
                n = self.con.execute("SELECT COUNT(*) FROM cards WHERE seen=1 AND due=?", (d.isoformat(),)).fetchone()[0]
            out.append(n)
        return out

    def total_reviews(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

    def random_distractors(self, card, field: str, n: int = 3) -> List[str]:
        """Ko'p tanlovli savol uchun boshqa kartalardan noto'g'ri variantlar (avval shu to'plamdan)."""
        rows = self.con.execute(
            f"SELECT DISTINCT {field} AS v FROM cards WHERE deck_id=? AND id<>? AND {field}<>'' AND {field}<>?",
            (card["deck_id"], card["id"], card[field])).fetchall()
        vals = [r["v"] for r in rows]
        if len(vals) < n:
            more = self.con.execute(f"SELECT DISTINCT {field} AS v FROM cards WHERE id<>? AND {field}<>'' "
                                    f"AND {field}<>? LIMIT 200", (card["id"], card[field])).fetchall()
            vals += [r["v"] for r in more if r["v"] not in vals]
        random.shuffle(vals)
        return vals[:n]
