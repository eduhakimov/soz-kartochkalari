"""Chuqur ssenariylar: SM-2 jadvali soxta sanalar bilan, import kodlashlari, eksport, o'qish sessiyasi (4 rejim)."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from soz_kartochkalari import cardio, srs  # noqa: E402
from soz_kartochkalari.db import DB  # noqa: E402


def test_sm2_schedule_over_simulated_months(tmp_path):
    db = DB(tmp_path / "k.db")
    did = db.add_deck("Test")
    cid = db.add_card(did, "apple", uz="olma")
    day = date(2026, 1, 1)
    plan = []
    for grade in (3, 3, 3, 1, 3, 4):
        new, due = db.answer(cid, grade, today=day)
        plan.append((day.isoformat(), new.interval))
        day = due                                  # foydalanuvchi aynan muddat kuni qaytadi
    assert [i for _, i in plan] == [1, 6, 15, 1, 1, 8]          # oxirgisi "Oson" (q=5)
    c = db.card(cid)
    assert c["lapses"] == 1 and c["seen"] == 1
    # navbat: muddati kelmagan karta bugun ko'rinmaydi, kelganda ko'rinadi
    assert not db.queue(did, day - timedelta(days=1), new_limit=0)
    assert [r["id"] for r in db.queue(did, day, new_limit=0)] == [cid]
    db.close()


def test_new_card_daily_limit(tmp_path):
    db = DB(tmp_path / "k.db")
    did = db.add_deck("Test")
    db.add_cards(did, [{"word": f"w{i}", "uz": f"s{i}"} for i in range(30)])
    today = date(2026, 3, 1)
    q = db.queue(did, today, new_limit=10)
    assert len(q) == 10
    for c in q[:4]:
        db.answer(c["id"], 3, today=today)
    assert len(db.queue(did, today, new_limit=10)) == 6           # 4 tasi o'rganildi, limit 10
    assert len(db.queue(did, today + timedelta(days=1), new_limit=10)) == 14   # 4 takror + 10 yangi
    db.close()


@pytest.mark.parametrize("enc", ["cp1251", "utf-8", "utf-8-sig", "utf-16"])
def test_import_encodings_even_and_odd_length(tmp_path, enc):
    for text in ("слово;перевод\nкот;mushuk\n", "слово;перевод\nкот;mushukk\n"):
        p = tmp_path / f"t_{enc}.csv"
        p.write_bytes(text.encode(enc))
        rows = cardio.read_table(str(p))
        assert rows == [["слово", "перевод"], ["кот", text.split(";")[-1].strip()]], enc


def test_import_anki_and_xlsx_roundtrip(tmp_path):
    anki = tmp_path / "anki.txt"
    anki.write_text("#separator:tab\n#html:false\napple\tolma\nbook\tkitob\n", encoding="utf-8")
    rows = cardio.read_table(str(anki))
    data = cardio.apply_mapping(rows, cardio.guess_mapping(rows), cardio.has_header(rows))
    assert [d["word"] for d in data] == ["apple", "book"] and data[0]["uz"] == "olma"
    from soz_kartochkalari.ui_extra import write_xlsx
    x = tmp_path / "IELTS papka" / "out.xlsx"
    x.parent.mkdir()
    write_xlsx(str(x), "IELTS: 150 [A/B]", ["word", "uz"], [["apple", "ol\x01ma"]], title="IELTS: 150")
    back = cardio.read_table(str(x))
    assert back[-1] == ["apple", "olma"]


def test_answer_checking_uzbek_apostrophes():
    assert srs.check_answer("o‘qituvchi", "oʻqituvchi") == "correct"
    assert srs.check_answer("O'QITUVCHI", "oʻqituvchi, ustoz") == "correct"
    assert srs.check_answer("ustoz", "oʻqituvchi; ustoz") == "correct"
    assert srs.check_answer("oqituvchi", "oʻqituvchi") == "close"
    assert srs.check_answer("talaba", "oʻqituvchi") == "wrong"
    assert srs.check_answer("", "x") == "wrong"


def test_corrupt_database_is_backed_up(tmp_path):
    f = tmp_path / "kartalar.db"
    f.write_bytes(b"garbage" * 200)
    db = DB(f)
    assert db.broken_backup and db.broken_backup.exists()
    assert db.decks() == []
    db.close()


# ----------------------------------------------------------------------------- interfeys
@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    from PySide6.QtWidgets import QApplication
    from uzkit import app as appmod
    from uzkit.settings import Settings
    appmod.META = appmod.load_meta()
    st = Settings(appmod.META["slug"] + "_scn")
    st.set("goal", "x")
    st.set("new_per_day", None)
    st.set("rate", "fast")
    st.set("auto_speak", "yes")
    appmod.SETTINGS = Settings(appmod.META["slug"] + "_scn")
    QApplication.instance() or QApplication([])
    from soz_kartochkalari import ui_extra, window as wmod
    monkeypatch.setattr(ui_extra, "_DEMO_DIRS", {})
    w = wmod.MainWindow()
    w.wmod = wmod
    yield w
    w.db.close()
    w.close()


def _deck(win, n=6):
    did = win.db.add_deck("Mevalar")
    words = [("apple", "olma"), ("pear", "nok"), ("grape", "uzum"), ("plum", "olxoʻri"), ("melon", "qovun"),
             ("cherry", "gilos")][:n]
    win.db.add_cards(did, [{"word": w, "uz": u} for w, u in words])
    return did


def test_ui_settings_with_wrong_types(win):
    assert win.goal() == 20 and win.new_limit() == 10


def test_ui_flip_session_and_grade_spam(win):
    did = _deck(win)
    win.start_study(did)
    st = win.study
    st.mode_grp.button(0).setChecked(True)
    st.show_card()
    assert len(st.queue) == 6
    first = st.card["id"]
    st.reveal()
    st.grade(1)                                   # "Yana": sessiya oxirida yana chiqadi
    st.grade(1)                                   # takroriy bosish: e'tiborsiz
    assert win.db.total_reviews() == 1 and len(st.queue) == 7
    while st.card is not None:
        st.reveal()
        st.grade(3)
    assert win.db.total_reviews() == 7
    assert win.db.card(first)["lapses"] == 0 and win.db.card(first)["seen"] == 1
    assert st.session == {"n": 7, "ok": 6}


def test_ui_type_and_choice_modes(win):
    did = _deck(win, 4)
    win.start_study(did)
    st = win.study
    st.mode_grp.button(1).setChecked(True)          # type
    st.show_card()
    st.answer.setText(st.card["word"].upper())
    st.check()
    st.check()
    assert st.answered == "correct" and win.db.total_reviews() == 1
    st.next()
    st.mode_grp.button(2).setChecked(True)          # choice
    st.show_card()
    right = st.choice_opts.index(st.card["uz"])
    wrong = next(i for i in range(len(st.choice_opts)) if i != right)
    st.choose(wrong)
    st.choose(right)                                # javobdan keyin boshqa variant bosilmaydi
    assert st.answered == "wrong" and win.db.total_reviews() == 2


def test_ui_export_xlsx_with_colon_in_deck_name(win, tmp_path, monkeypatch):
    did = _deck(win, 2)
    win.db.rename_deck(did, "IELTS: 150 / 2026")
    out = tmp_path / "e.xlsx"
    monkeypatch.setattr(win.wmod.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    errs = []
    monkeypatch.setattr(win.wmod, "error", lambda parent, text, *a: errs.append(text))
    win.export_deck(did, "xlsx")
    assert not errs and out.exists()
    assert ["apple", "", "olma", "", ""] in cardio.read_table(str(out))


@pytest.mark.parametrize("raw", ["[1, 2]", "null", "5", "{broken"])
def test_settings_file_with_wrong_root_is_reset(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from uzkit.settings import Settings
    f = tmp_path / "BahtiyorSoft" / "x_root" / "settings.json"
    f.parent.mkdir(parents=True)
    f.write_text(raw, encoding="utf-8")
    s = Settings("x_root")
    assert s.get("k", 1) == 1 and f.with_suffix(".broken.json").exists()
