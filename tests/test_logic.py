import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from soz_kartochkalari import cardio, srs
from soz_kartochkalari.db import DB

DECKS = ROOT / "assets" / "decks"


# ---------------------------------------------------------------- SM-2
def test_sm2_sequence_good():
    s = srs.CardState()
    s = srs.sm2(s, 4)
    assert (s.reps, s.interval) == (1, 1) and s.ef == pytest.approx(2.5)
    s = srs.sm2(s, 4)
    assert (s.reps, s.interval) == (2, 6)
    s = srs.sm2(s, 4)
    assert (s.reps, s.interval) == (3, 15)     # 6 * 2.5
    s = srs.sm2(s, 5)
    assert s.interval == 49 and s.ef == pytest.approx(2.6)          # 15 * 2.5 * 1.3
    h = srs.sm2(srs.CardState(reps=3, interval=15, ef=2.5), 3)
    assert h.interval == 18                                          # 15 * 1.2


def test_sm2_ef_changes_and_floor():
    assert srs.sm2(srs.CardState(), 3).ef == pytest.approx(2.36)
    assert srs.sm2(srs.CardState(), 5).ef == pytest.approx(2.6)
    s = srs.CardState(ef=1.35)
    for _ in range(5):
        s = srs.sm2(s, 0)
    assert s.ef == srs.MIN_EF


def test_sm2_lapse_resets():
    s = srs.CardState(reps=4, interval=40, ef=2.5)
    n = srs.sm2(s, 1)
    assert n.reps == 0 and n.interval == 1 and n.lapses == 1
    n2 = srs.sm2(n, 4)
    assert n2.reps == 1 and n2.interval == 1
    with pytest.raises(ValueError):
        srs.sm2(s, 6)


def test_review_dates_and_preview():
    st, due = srs.review(srs.CardState(), 3, date(2026, 1, 1))
    assert due == date(2026, 1, 2)
    p = srs.preview_intervals(srs.CardState(reps=2, interval=6, ef=2.5))
    assert p[1] == 1 and p[2] == 7 and p[3] == 15 and p[4] == 20
    assert len(set(srs.preview_intervals(srs.CardState()).values())) >= 2


def test_check_answer():
    assert srs.check_answer("Approach", "approach") == "correct"
    assert srs.check_answer("  approach ", "approach") == "correct"
    assert srs.check_answer("aproach", "approach") == "close"
    assert srs.check_answer("table", "approach") == "wrong"
    assert srs.check_answer("", "x") == "wrong"
    assert srs.check_answer("usul", "yo'l, usul") == "correct"
    assert srs.check_answer("yoʻl", "yo'l, usul") == "correct"
    assert srs.check_answer("anti aliasing", "anti-aliasing") == "correct"


def test_streak():
    t = date(2026, 5, 10)
    met = {t - timedelta(days=i) for i in (1, 2, 3, 5)}
    assert srs.streak(met, t) == 3
    assert srs.streak(met | {t}, t) == 4
    assert srs.streak(set(), t) == 0
    assert srs.best_streak(met | {t}) == 4


# ---------------------------------------------------------------- built-in decks
@pytest.mark.parametrize("key,count", [("common300", 300), ("ielts150", 150), ("graphics100", 100)])
def test_builtin_decks(key, count):
    rows = cardio.load_builtin(DECKS, key)
    assert len(rows) == count
    words = [r["word"].lower() for r in rows]
    assert len(set(words)) == count
    for r in rows:
        assert r["word"] and r["uz"] and r["ru"] and r["ipa"] and r["example"]
        assert "|" not in r["example"]


# ---------------------------------------------------------------- DB, navbat, statistika
def make_db():
    return DB(Path(tempfile.mkdtemp()) / "k.db")


def test_queue_and_answer():
    db = make_db()
    did = db.add_deck("D")
    n = db.add_cards(did, [{"word": f"w{i}", "uz": f"u{i}"} for i in range(30)] + [{"word": "W1", "uz": "x"}])
    assert n == 30           # takroriy (W1 ~ w1) o'tkazib yuborildi
    t = date(2026, 1, 10)
    q = db.queue(did, t, new_limit=10)
    assert len(q) == 10
    for c in q[:4]:
        db.answer(c["id"], 3, today=t)
    assert db.new_today(t) == 4
    assert len(db.queue(did, t, new_limit=10)) == 6      # 4 ta yangi o'rganildi
    t2 = t + timedelta(days=1)
    q2 = db.queue(did, t2, new_limit=0)
    assert len(q2) == 4                                   # 1 kundan keyin takrorlash
    counts = db.deck_counts(did, t2)
    assert counts == {"total": 30, "new": 26, "due": 4, "mature": 0}
    assert db.reviews_per_day(t, t)[t] == 4
    assert db.accuracy(t) == 1.0
    assert db.categories()["learning"] == 4
    f = db.forecast(t, 3)
    assert f == [0, 4, 0]
    assert db.days_meeting_goal(4) == {t}


def test_distractors_and_search():
    db = make_db()
    did = db.add_deck("D")
    db.add_cards(did, [{"word": f"w{i}", "uz": f"u{i}"} for i in range(6)])
    c = db.cards(did)[0]
    ds = db.random_distractors(c, "uz", 3)
    assert len(ds) == 3 and c["uz"] not in ds
    assert len(db.cards(did, "w3")) == 1


# ---------------------------------------------------------------- import / eksport
def test_import_csv_semicolon_with_header(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("word;uz;ru\napple;olma;яблоко\nbook;kitob;книга\n", encoding="utf-8-sig")
    rows = cardio.read_table(str(p))
    assert cardio.has_header(rows)
    m = cardio.guess_mapping(rows)
    data = cardio.apply_mapping(rows, m, True)
    assert data[0]["word"] == "apple" and data[0]["uz"] == "olma" and data[1]["ru"] == "книга"


def test_import_anki_tsv(tmp_path):
    p = tmp_path / "anki.txt"
    p.write_text("#separator:tab\n#html:false\nhouse\tuy\nwater\tsuv\n", encoding="utf-8")
    rows = cardio.read_table(str(p))
    assert rows == [["house", "uy"], ["water", "suv"]]
    data = cardio.apply_mapping(rows, cardio.guess_mapping(rows), False)
    assert data[1] == {"word": "water", "ipa": "", "uz": "suv", "ru": "", "example": ""}


def test_xlsx_roundtrip_and_tsv(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from soz_kartochkalari.ui_extra import write_xlsx
    rows = [["apple", "ˈæpl", "olma", "яблоко", "An apple a day."]]
    p = tmp_path / "a.xlsx"
    write_xlsx(str(p), "D", ["English word", "IPA", "Uzbek", "Russian", "Example"], rows)
    back = cardio.read_table(str(p))
    assert back[1] == rows[0]
    m = cardio.guess_mapping(back)
    assert cardio.apply_mapping(back, m, True)[0]["uz"] == "olma"
    t = tmp_path / "a.txt"
    cardio.write_tsv(str(t), rows)
    assert cardio.read_table(str(t)) == rows
    c = tmp_path / "a.csv"
    cardio.write_csv(str(c), ["word", "ipa", "uz", "ru", "example"], rows)
    assert cardio.read_table(str(c))[1] == rows[0]


def test_tts_language_detection():
    from soz_kartochkalari.tts import Speaker
    assert Speaker.is_english("409")
    assert Speaker.is_english("809;409")
    assert not Speaker.is_english("419")
    assert not Speaker.is_english("")


def test_ui_study_modes():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from uzkit import app as appmod
    from uzkit.settings import Settings
    appmod.META = appmod.load_meta()
    appmod.SETTINGS = Settings(appmod.META["slug"] + "_test")
    appmod.SETTINGS.set("auto_speak", False)
    from soz_kartochkalari import window
    w = window.MainWindow()
    s = w.study
    s.load_queue()
    assert s.queue
    s.reveal()
    s.grade(3)
    assert w.db.total_reviews() >= 1
    for i in range(1, 4):
        s.mode_grp.button(i).click()
        if i == 1:
            s.answer.setText(s.card["word"])
            s.check()
            assert s.answered == "correct"
            s.next()
        if i == 2:
            s.choose(0)
            assert s.answered in ("correct", "wrong")
    for i in range(5):
        w.set_page(i)
    window.CardDialog(w, w.db.cards()[0]).close()
    w.close()
