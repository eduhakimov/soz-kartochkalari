"""Asosiy oyna: chap belgilar paneli; to'plamlar, mashq, kartalar, statistika, sozlamalar."""
import random
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from uzkit import app as appmod
from uzkit.i18n import language, register, tr
from uzkit.paths import resource
from uzkit.widgets import Card, ask, danger_button, error, header, info, open_path, primary_button, warn
from uzkit.window import BaseMainWindow

from . import cardio, srs
from .db import DB, FIELDS
from .strings import STRINGS
from .tts import Speaker
from .ui_extra import (BarChart, DonutChart, ProgressRing, accent, app_data_dir, esc, icon, is_demo, mix, pal,
                       write_xlsx)

register(STRINGS)
SLUG = "soz-kartochkalari"
MODES = ["flip", "type", "choice", "listen"]
GRADE_COLORS = {1: "#e03131", 2: "#e8590c", 3: "#2f9e44", 4: "#1c7ed6"}


def today() -> date:
    return date.today()


def days_text(n: int) -> str:
    if n <= 0:
        return tr("today_short")
    if n < 30:
        return tr("n_d", n=n)
    if n < 365:
        return tr("n_mo", n=round(n / 30))
    return tr("n_y", n=round(n / 365, 1))


def icon_button(name, tip, text=""):
    b = QPushButton(text)
    b.setIcon(icon(name, pal()["text"]))
    b.setIconSize(QSize(18, 18))
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    if not text:
        b.setFixedWidth(40)
    return b


# =========================================================================== karta dialogi
class CardDialog(QDialog):
    def __init__(self, win, card=None, deck_id=None):
        super().__init__(win)
        self.win = win
        self.card = card
        self.setWindowTitle(tr("edit_card") if card else tr("add_card"))
        self.setMinimumWidth(500)
        l = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(9)
        self.deck = QComboBox()
        for d in win.db.decks():
            self.deck.addItem(d["name"], d["id"])
        self.word = QLineEdit()
        self.word.setPlaceholderText("e.g. approach")
        self.ipa = QLineEdit()
        self.ipa.setPlaceholderText("əˈprəʊtʃ")
        self.uz = QLineEdit()
        self.ru = QLineEdit()
        self.example = QPlainTextEdit()
        self.example.setFixedHeight(56)
        img_row = QHBoxLayout()
        self.image = QLineEdit()
        self.image.setReadOnly(True)
        self.image.setPlaceholderText(tr("no_image"))
        bi = QPushButton(tr("choose"))
        bc = QPushButton(tr("clear"))
        img_row.addWidget(self.image, 1)
        img_row.addWidget(bi)
        img_row.addWidget(bc)
        bi.clicked.connect(self._pick)
        bc.clicked.connect(lambda: self.image.clear())
        form.addRow(tr("deck"), self.deck)
        form.addRow(tr("f_word"), self.word)
        form.addRow(tr("f_ipa"), self.ipa)
        form.addRow(tr("f_uz"), self.uz)
        form.addRow(tr("f_ru"), self.ru)
        form.addRow(tr("f_example"), self.example)
        form.addRow(tr("f_image"), img_row)
        l.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("save"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        if card:
            self.deck.setCurrentIndex(max(0, self.deck.findData(card["deck_id"])))
            for f in ("word", "ipa", "uz", "ru"):
                getattr(self, f).setText(card[f])
            self.example.setPlainText(card["example"])
            self.image.setText(card["image"] or "")
        elif deck_id:
            self.deck.setCurrentIndex(max(0, self.deck.findData(deck_id)))

    def _pick(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("f_image"), str(Path.home()),
                                           tr("images") + " (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if p:
            self.image.setText(p)

    def _ok(self):
        if not self.word.text().strip() or not self.uz.text().strip():
            warn(self, tr("need_word"))
            return
        if self.deck.currentData() is None:
            warn(self, tr("need_deck"))
            return
        self.accept()

    def values(self):
        return {"deck_id": self.deck.currentData(), "word": self.word.text().strip(), "ipa": self.ipa.text().strip(),
                "uz": self.uz.text().strip(), "ru": self.ru.text().strip(),
                "example": self.example.toPlainText().strip(), "image": self.image.text().strip()}


class ImportDialog(QDialog):
    """Ustunlarni moslash va oldindan ko'rish."""

    def __init__(self, win, rows, name):
        super().__init__(win)
        self.rows = rows
        self.setWindowTitle(tr("import_title"))
        self.resize(760, 520)
        l = QVBoxLayout(self)
        top = QFormLayout()
        self.deck = QComboBox()
        self.deck.addItem(tr("new_deck_named", name=name), None)
        for d in win.db.decks():
            self.deck.addItem(d["name"], d["id"])
        top.addRow(tr("import_into"), self.deck)
        self.header_cb = QCheckBox(tr("first_row_header"))
        self.header_cb.setChecked(cardio.has_header(rows))
        top.addRow("", self.header_cb)
        l.addLayout(top)
        width = max(len(r) for r in rows)
        mapping = cardio.guess_mapping(rows)
        maprow = QHBoxLayout()
        self.combos = []
        for i in range(width):
            cb = QComboBox()
            cb.addItem(tr("skip"), "")
            for f in FIELDS:
                cb.addItem(tr("f_" + f), f)
            cb.setCurrentIndex(max(0, cb.findData(mapping.get(i, ""))))
            self.combos.append(cb)
            maprow.addWidget(cb)
        lab = QLabel(tr("map_columns"))
        lab.setObjectName("Muted")
        l.addWidget(lab)
        l.addLayout(maprow)
        t = QTableWidget(min(len(rows), 50), width)
        t.horizontalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, row in enumerate(rows[:50]):
            for c, v in enumerate(row):
                t.setItem(r, c, QTableWidgetItem(v))
        l.addWidget(t, 1)
        self.count = QLabel(tr("rows_found", n=len(rows)))
        self.count.setObjectName("Muted")
        l.addWidget(self.count)
        self.name = name
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("import"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def mapping(self):
        return {i: cb.currentData() for i, cb in enumerate(self.combos) if cb.currentData()}

    def _ok(self):
        if "word" not in self.mapping().values():
            warn(self, tr("need_word_col"))
            return
        self.accept()


# =========================================================================== bosh sahifa
class DeckTile(QFrame):
    study = Signal(int)
    menu = Signal(int, object)

    def __init__(self, deck, counts):
        super().__init__()
        self.did = deck["id"]
        self.setObjectName("DeckTile")
        self.setMinimumHeight(132)
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 14, 16, 14)
        l.setSpacing(6)
        top = QHBoxLayout()
        t = QLabel(deck["name"])
        t.setObjectName("DeckName")
        t.setWordWrap(True)
        top.addWidget(t, 1)
        mb = QToolButton()
        mb.setIcon(icon("grid", pal()["muted"], 16))
        mb.setAutoRaise(True)
        mb.setToolTip(tr("deck_actions"))
        mb.clicked.connect(lambda: self.menu.emit(self.did, mb.mapToGlobal(mb.rect().bottomLeft())))
        top.addWidget(mb, 0, Qt.AlignTop)
        l.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(14)
        for key, n, col in (("c_due", counts["due"], "#e8590c"), ("c_new", counts["new"], "#1c7ed6"),
                            ("c_total", counts["total"], pal()["muted"])):
            v = QLabel(f"<span style='font-size:15pt; font-weight:700; color:{col}'>{n}</span><br>"
                       f"<span style='color:{pal()['muted']}'>{tr(key)}</span>")
            row.addWidget(v)
        row.addStretch(1)
        b = QPushButton(tr("study"))
        b.setObjectName("Primary" if counts["due"] or counts["new"] else "")
        b.setEnabled(counts["total"] > 0)
        b.clicked.connect(lambda: self.study.emit(self.did))
        row.addWidget(b, 0, Qt.AlignBottom)
        l.addLayout(row)
        bar = QFrame()
        bar.setFixedHeight(5)
        frac = counts["mature"] / counts["total"] if counts["total"] else 0
        bar.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent()}, "
                          f"stop:{max(0.001, frac):.3f} {accent()}, stop:{min(0.999, frac + 0.001):.3f} "
                          f"{pal()['surface2']}, stop:1 {pal()['surface2']}); border-radius: 2px;")
        bar.setToolTip(tr("mature_share", p=round(frac * 100)))
        l.addWidget(bar)


class HomePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        hero = QFrame()
        hero.setObjectName("HomeHero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(22, 18, 22, 18)
        hl.setSpacing(20)
        self.ring = ProgressRing(104, 11)
        hl.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.greet = QLabel()
        self.greet.setObjectName("HeroTitle")
        self.greet.setWordWrap(True)
        self.sub = QLabel()
        self.sub.setObjectName("HeroSub")
        self.sub.setWordWrap(True)
        col.addWidget(self.greet)
        col.addWidget(self.sub)
        srow = QHBoxLayout()
        srow.setSpacing(18)
        self.streak = QLabel()
        self.streak.setObjectName("HeroStat")
        self.due_lbl = QLabel()
        self.due_lbl.setObjectName("HeroStat")
        srow.addWidget(self.streak)
        srow.addWidget(self.due_lbl)
        srow.addStretch(1)
        col.addLayout(srow)
        hl.addLayout(col, 1)
        self.go = primary_button(tr("start_review"))
        self.go.setObjectName("HeroButton")
        self.go.setMinimumHeight(44)
        self.go.clicked.connect(lambda: win.start_study(None))
        hl.addWidget(self.go, 0, Qt.AlignVCenter)
        lay.addWidget(hero)
        bar = QHBoxLayout()
        t = QLabel(tr("my_decks"))
        t.setObjectName("SectionTitle")
        bar.addWidget(t)
        bar.addStretch(1)
        nb = icon_button("plus", tr("new_deck"), tr("new_deck"))
        nb.clicked.connect(win.new_deck)
        ib = icon_button("import", tr("import_file"), tr("import_file"))
        ib.clicked.connect(win.import_file)
        bb = QPushButton(tr("builtin_decks"))
        bm = QMenu(self)
        for key, d in cardio.BUILTIN_DECKS.items():
            bm.addAction(d["name"][language()], lambda k=key: win.add_builtin(k))
        bb.setMenu(bm)
        for b in (nb, ib, bb):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(12)
        self.scroll.setWidget(host)
        lay.addWidget(self.scroll, 1)

    def refresh(self):
        db, w = self.win.db, self.win
        t = today()
        goal = w.goal()
        done = db.reviews_per_day(t, t).get(t, 0)
        self.ring.set_value(min(1.0, done / goal) if goal else 0, None, f"{done}/{goal}")
        self.greet.setText(tr("greet_done") if done >= goal else tr("greet"))
        self.sub.setText(tr("goal_line", n=goal))
        s = srs.streak(db.days_meeting_goal(goal), t)
        self.streak.setText(tr("streak_n", n=s))
        q = db.queue(None, t, w.new_limit())
        self.due_lbl.setText(tr("queue_n", n=len(q)))
        self.go.setEnabled(bool(q))
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        decks = db.decks()
        cols = max(1, min(3, self.scroll.viewport().width() // 300))
        for i, d in enumerate(decks):
            tile = DeckTile(d, db.deck_counts(d["id"], t))
            tile.study.connect(w.start_study)
            tile.menu.connect(self._deck_menu)
            self.grid.addWidget(tile, i // cols, i % cols)
        if not decks:
            e = QLabel(tr("no_decks"))
            e.setObjectName("Muted")
            e.setWordWrap(True)
            e.setAlignment(Qt.AlignCenter)
            e.setMinimumHeight(140)
            self.grid.addWidget(e, 0, 0)
        self.grid.setRowStretch(self.grid.rowCount(), 1)
        self._cols = cols

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols = max(1, min(3, self.scroll.viewport().width() // 300))
        if getattr(self, "_cols", None) != cols:
            QTimer.singleShot(0, self.refresh)

    def _deck_menu(self, did, pos):
        m = QMenu(self)
        m.addAction(tr("study"), lambda: self.win.start_study(did))
        m.addAction(tr("show_cards"), lambda: self.win.show_cards(did))
        m.addAction(tr("add_card"), lambda: self.win.add_card(did))
        m.addSeparator()
        m.addAction(tr("rename"), lambda: self.win.rename_deck(did))
        ex = m.addMenu(tr("export"))
        ex.addAction("CSV", lambda: self.win.export_deck(did, "csv"))
        ex.addAction("Excel", lambda: self.win.export_deck(did, "xlsx"))
        ex.addAction(tr("tsv_anki"), lambda: self.win.export_deck(did, "tsv"))
        m.addSeparator()
        m.addAction(tr("delete_deck"), lambda: self.win.delete_deck(did))
        m.exec(pos)


# =========================================================================== mashq
class FlashCard(QFrame):
    """Katta karta: old tomon (so'z) va orqa tomon (tarjima, misol, rasm)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("FlashCard")
        self.setMinimumHeight(250)
        l = QVBoxLayout(self)
        l.setContentsMargins(30, 22, 30, 22)
        l.setSpacing(6)
        self.top = QLabel()
        self.top.setObjectName("CardHint")
        self.top.setAlignment(Qt.AlignCenter)
        l.addWidget(self.top)
        l.addStretch(1)
        self.word = QLabel()
        self.word.setObjectName("CardWord")
        self.word.setAlignment(Qt.AlignCenter)
        self.word.setWordWrap(True)
        l.addWidget(self.word)
        self.ipa = QLabel()
        self.ipa.setObjectName("CardIpa")
        self.ipa.setAlignment(Qt.AlignCenter)
        l.addWidget(self.ipa)
        self.sep = QFrame()
        self.sep.setObjectName("CardSep")
        self.sep.setFixedHeight(1)
        l.addSpacing(6)
        l.addWidget(self.sep)
        l.addSpacing(6)
        self.back = QLabel()
        self.back.setObjectName("CardBack")
        self.back.setAlignment(Qt.AlignCenter)
        self.back.setWordWrap(True)
        self.back.setTextFormat(Qt.RichText)
        l.addWidget(self.back)
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        l.addWidget(self.img)
        l.addStretch(1)


class StudyPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.queue = []
        self.pos = 0
        self.card = None
        self.revealed = False
        self.answered = None
        self.session = {"n": 0, "ok": 0}
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.deck = QComboBox()
        self.deck.setMinimumWidth(240)
        top.addWidget(self.deck)
        self.mode_grp = QButtonGroup(self)
        for i, m in enumerate(MODES):
            b = QPushButton(tr("mode_" + m))
            b.setCheckable(True)
            b.setObjectName("Seg")
            self.mode_grp.addButton(b, i)
            top.addWidget(b)
        self.mode_grp.button(0).setChecked(True)
        top.addStretch(1)
        self.progress = QLabel()
        self.progress.setObjectName("Muted")
        top.addWidget(self.progress)
        lay.addLayout(top)
        self.bar = QFrame()
        self.bar.setObjectName("StudyBar")
        self.bar.setFixedHeight(4)
        lay.addWidget(self.bar)

        self.fc = FlashCard()
        lay.addWidget(self.fc, 1)
        # javob maydoni (yozish / tinglash)
        self.answer_row = QWidget()
        ar = QHBoxLayout(self.answer_row)
        ar.setContentsMargins(0, 0, 0, 0)
        self.answer = QLineEdit()
        self.answer.setObjectName("AnswerEdit")
        self.answer.setPlaceholderText(tr("type_answer"))
        self.check_btn = primary_button(tr("check"))
        ar.addWidget(self.answer, 1)
        ar.addWidget(self.check_btn)
        lay.addWidget(self.answer_row)
        # variantlar
        self.choice_box = QWidget()
        cg = QGridLayout(self.choice_box)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setSpacing(8)
        self.choice_btns = []
        for i in range(4):
            b = QPushButton()
            b.setObjectName("Choice")
            b.setMinimumHeight(46)
            b.clicked.connect(lambda _=False, k=i: self.choose(k))
            self.choice_btns.append(b)
            cg.addWidget(b, i // 2, i % 2)
        lay.addWidget(self.choice_box)
        # baholash tugmalari
        self.grade_box = QWidget()
        gl = QHBoxLayout(self.grade_box)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(10)
        self.grade_btns = {}
        for g in (1, 2, 3, 4):
            b = QPushButton()
            b.setObjectName("Grade")
            b.setMinimumHeight(52)
            b.setStyleSheet(f"QPushButton#Grade {{ border-top: 3px solid {GRADE_COLORS[g]}; }}")
            b.clicked.connect(lambda _=False, gg=g: self.grade(gg))
            self.grade_btns[g] = b
            gl.addWidget(b)
        lay.addWidget(self.grade_box)
        self.flip_row = QWidget()
        fr = QHBoxLayout(self.flip_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self.speak_btn = icon_button("speaker", tr("pronounce") + " (P)")
        fr.addWidget(self.speak_btn)
        fr.addStretch(1)
        self.flip_btn = primary_button(tr("show_answer"))
        self.flip_btn.setMinimumHeight(44)
        self.flip_btn.setMinimumWidth(260)
        fr.addWidget(self.flip_btn)
        fr.addStretch(1)
        self.next_btn = QPushButton(tr("next_card"))
        fr.addWidget(self.next_btn)
        lay.addWidget(self.flip_row)
        self.hint = QLabel(tr("keys_hint"))
        self.hint.setObjectName("Muted")
        self.hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.hint)

        self.deck.currentIndexChanged.connect(lambda *_: self.load_queue())
        self.mode_grp.idClicked.connect(lambda *_: self.show_card())
        self.flip_btn.clicked.connect(self.reveal)
        self.next_btn.clicked.connect(self.next)
        self.check_btn.clicked.connect(self.check)
        self.answer.returnPressed.connect(self._enter)
        self.speak_btn.clicked.connect(self.speak)
        for key, fn in (("Space", self._space), ("1", lambda: self._num(1)), ("2", lambda: self._num(2)),
                        ("3", lambda: self._num(3)), ("4", lambda: self._num(4)), ("P", self.speak),
                        ("Return", self._enter), ("Enter", self._enter)):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.WidgetWithChildrenShortcut)
            s.activated.connect(fn)

    # ------------------------------------------------------------------ navbat
    def fill_decks(self, select=None):
        cur = select if select is not None else self.deck.currentData()
        self.deck.blockSignals(True)
        self.deck.clear()
        self.deck.addItem(tr("all_decks"), 0)
        for d in self.win.db.decks():
            self.deck.addItem(d["name"], d["id"])
        self.deck.setCurrentIndex(max(0, self.deck.findData(cur or 0)))
        self.deck.blockSignals(False)

    def load_queue(self):
        did = self.deck.currentData() or None
        self.queue = list(self.win.db.queue(did, today(), self.win.new_limit(), shuffle_seed=random.randint(0, 10**6)))
        self.pos = 0
        self.session = {"n": 0, "ok": 0}
        self.show_card()

    def mode(self):
        return MODES[max(0, self.mode_grp.checkedId())]

    def _update_progress(self):
        total = len(self.queue)
        self.progress.setText(tr("progress_n", i=min(self.pos + 1, total), n=total) if total else "")
        frac = self.pos / total if total else 0
        a, s2 = accent(), pal()["surface2"]
        f1 = max(0.001, min(0.998, frac))
        self.bar.setStyleSheet(f"QFrame#StudyBar {{ border-radius: 2px; background: qlineargradient(x1:0, y1:0, "
                               f"x2:1, y2:0, stop:0 {a}, stop:{f1:.3f} {a}, stop:{f1 + 0.001:.3f} {s2}, stop:1 {s2}); }}")

    def show_card(self):
        self._update_progress()
        self.revealed = False
        self.answered = None
        self.answer.clear()
        fc = self.fc
        if self.pos >= len(self.queue):
            self.card = None
            fc.top.setText("")
            if self.session["n"]:
                fc.word.setText(tr("session_done"))
                acc = round(self.session["ok"] * 100 / self.session["n"])
                fc.ipa.setText(tr("session_stats", n=self.session["n"], p=acc))
            else:
                fc.word.setText(tr("nothing_due"))
                fc.ipa.setText(tr("nothing_due_sub"))
            fc.back.setText("")
            fc.img.clear()
            fc.sep.hide()
            for w in (self.answer_row, self.choice_box, self.grade_box, self.flip_btn, self.next_btn,
                      self.speak_btn):
                w.hide()
            return
        self.card = self.win.db.card(self.queue[self.pos]["id"])
        if self.card is None:
            self.pos += 1
            return self.show_card()
        c, m = self.card, self.mode()
        fc.sep.hide()
        fc.back.setText("")
        fc.img.clear()
        self.speak_btn.show()
        self.next_btn.hide()
        self.grade_box.hide()
        self.choice_box.setVisible(m == "choice")
        self.answer_row.setVisible(m in ("type", "listen"))
        self.flip_btn.setVisible(m == "flip")
        self.flip_btn.setEnabled(True)
        tag = tr("tag_new") if not c["seen"] else tr("tag_review")
        if m == "flip":
            fc.top.setText(tag)
            fc.word.setText(c["word"])
            fc.ipa.setText(f"/{c['ipa']}/" if c["ipa"] else "")
            if self.win.settings.get("auto_speak", True) and not is_demo():
                self.speak()
        elif m == "type":
            fc.top.setText(tr("type_prompt"))
            fc.word.setText(c["uz"])
            fc.ipa.setText(c["ru"])
            self.answer.setFocus()
        elif m == "listen":
            fc.top.setText(tr("listen_prompt"))
            fc.word.setText("?")
            fc.ipa.setText(tr("listen_sub"))
            self.answer.setFocus()
            QTimer.singleShot(250, self.speak)
        else:
            fc.top.setText(tr("choice_prompt"))
            fc.word.setText(c["word"])
            fc.ipa.setText(f"/{c['ipa']}/" if c["ipa"] else "")
            opts = self.win.db.random_distractors(c, "uz", 3) + [c["uz"]]
            random.shuffle(opts)
            self.choice_opts = opts
            for i, b in enumerate(self.choice_btns):
                if i < len(opts):
                    b.setText(f"{i + 1}.  {opts[i]}")
                    b.setProperty("state", "")
                    b.setEnabled(True)
                    b.show()
                else:
                    b.hide()
                b.style().unpolish(b)
                b.style().polish(b)
        self._grade_labels()

    def _grade_labels(self):
        c = self.card
        if not c:
            return
        prev = srs.preview_intervals(srs.CardState(c["reps"], c["interval"], c["ef"], c["lapses"]))
        for g, b in self.grade_btns.items():
            b.setText(f"{g}  {tr('g_' + str(g))}\n{days_text(prev[g]) if g > 1 else tr('again_sub')}")

    def _show_back(self, verdict=None):
        c, fc = self.card, self.fc
        fc.sep.show()
        fc.word.setText(c["word"])
        fc.ipa.setText(f"/{c['ipa']}/" if c["ipa"] else "")
        parts = []
        if verdict:
            col = {"correct": "#2f9e44", "close": "#e8590c", "wrong": "#e03131"}[verdict]
            parts.append(f"<span style='color:{col}; font-weight:700'>{esc(tr('v_' + verdict))}</span>")
        parts.append(f"<span style='font-size:17pt; font-weight:600'>{esc(c['uz'])}</span>")
        if c["ru"]:
            parts.append(f"<span style='color:{pal()['muted']}; font-size:12pt'>{esc(c['ru'])}</span>")
        if c["example"]:
            parts.append(f"<i>{esc(c['example'])}</i>")
        fc.back.setText("<br>".join(parts))
        if c["image"]:
            p = Path(c["image"])
            if p.is_file():
                pm = QPixmap(str(p))
                if not pm.isNull():
                    fc.img.setPixmap(pm.scaled(260, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def reveal(self):
        if not self.card or self.revealed:
            return
        self.revealed = True
        self._show_back()
        self.flip_btn.hide()
        self.grade_box.show()

    def check(self):
        if not self.card or self.answered:
            return
        verdict = srs.check_answer(self.answer.text(), self.card["word"])
        self.answered = verdict
        self.revealed = True
        self._show_back(verdict)
        self.speak()
        grade = {"correct": 3, "close": 2, "wrong": 1}[verdict]
        self._record(grade)
        self.next_btn.show()
        self.next_btn.setFocus()

    def choose(self, k):
        if not self.card or self.answered:
            return
        if k >= len(self.choice_opts):
            return
        ok = self.choice_opts[k] == self.card["uz"]
        self.answered = "correct" if ok else "wrong"
        for i, b in enumerate(self.choice_btns):
            if i < len(self.choice_opts):
                st = "right" if self.choice_opts[i] == self.card["uz"] else ("wrong" if i == k else "")
                b.setProperty("state", st)
                b.style().unpolish(b)
                b.style().polish(b)
        self.revealed = True
        self._show_back(self.answered)
        self._record(3 if ok else 1)
        self.next_btn.show()
        self.next_btn.setFocus()

    def grade(self, g):
        if not self.card or not self.revealed or self.answered:
            return
        self.answered = "graded"
        self._record(g)
        self.next()

    def _record(self, g):
        if is_demo():
            return
        self.win.db.answer(self.card["id"], g, self.mode())
        self.session["n"] += 1
        self.session["ok"] += 1 if g > 1 else 0
        if g == 1:
            self.queue.append(self.queue[self.pos])      # xato javob: sessiya oxirida yana
        self.win.data_changed()

    def next(self):
        if not self.card:
            return
        if not self.answered:
            return
        self.pos += 1
        self.show_card()

    def speak(self):
        if self.card:
            self.win.speaker.speak(self.card["word"])

    def _space(self):
        if self.answer.hasFocus():
            self.answer.insert(" ")
            return
        if self.mode() == "flip" and not self.revealed:
            self.reveal()
        elif self.answered:
            self.next()

    def _num(self, n):
        if self.answer.hasFocus():
            self.answer.insert(str(n))
            return
        if self.mode() == "choice" and not self.answered:
            self.choose(n - 1)
        elif self.mode() == "flip" and self.revealed and not self.answered:
            self.grade(n)

    def _enter(self):
        if self.mode() in ("type", "listen") and not self.answered:
            self.check()
        elif self.answered:
            self.next()
        elif self.mode() == "flip" and not self.revealed:
            self.reveal()


# =========================================================================== kartalar
class CardsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.deck = QComboBox()
        self.deck.setMinimumWidth(240)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search_ph"))
        self.search.addAction(icon("search", pal()["muted"], 16), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.deck)
        top.addWidget(self.search, 1)
        self.add = primary_button(tr("add_card"))
        self.add.setIcon(icon("plus", "#ffffff"))
        top.addWidget(self.add)
        lay.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("f_word"), tr("f_ipa"), tr("f_uz"), tr("f_ru"), tr("next_due"),
                                              tr("deck")])
        hh = self.table.horizontalHeader()
        for i in range(6):
            hh.setSectionResizeMode(i, QHeaderView.Stretch if i in (0, 2, 3) else QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.table, 1)
        bot = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName("Muted")
        bot.addWidget(self.count, 1)
        self.b_speak = icon_button("speaker", tr("pronounce"))
        self.b_edit = icon_button("edit", tr("edit"))
        self.b_del = icon_button("trash", tr("delete"))
        self.b_exp = icon_button("export", tr("export"), tr("export"))
        em = QMenu(self)
        em.addAction("CSV", lambda: self.win.export_deck(self.deck.currentData() or None, "csv"))
        em.addAction("Excel", lambda: self.win.export_deck(self.deck.currentData() or None, "xlsx"))
        em.addAction(tr("tsv_anki"), lambda: self.win.export_deck(self.deck.currentData() or None, "tsv"))
        self.b_exp.setMenu(em)
        self.b_imp = icon_button("import", tr("import_file"), tr("import_file"))
        for b in (self.b_speak, self.b_edit, self.b_del, self.b_exp, self.b_imp):
            bot.addWidget(b)
        lay.addLayout(bot)
        self.deck.currentIndexChanged.connect(lambda *_: self.refresh())
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda *_: self._t.start(250))
        self.add.clicked.connect(lambda: self.win.add_card(self.deck.currentData() or None))
        self.b_edit.clicked.connect(self.edit)
        self.b_del.clicked.connect(self.delete)
        self.b_speak.clicked.connect(self.speak)
        self.b_imp.clicked.connect(self.win.import_file)
        for key, fn in (("Delete", self.delete), ("F2", self.edit), ("Ctrl+N", lambda: self.add.click())):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.WidgetWithChildrenShortcut)
            s.activated.connect(fn)

    def fill_decks(self, select=None):
        cur = select if select is not None else self.deck.currentData()
        self.deck.blockSignals(True)
        self.deck.clear()
        self.deck.addItem(tr("all_decks"), 0)
        for d in self.win.db.decks():
            self.deck.addItem(d["name"], d["id"])
        self.deck.setCurrentIndex(max(0, self.deck.findData(cur or 0)))
        self.deck.blockSignals(False)

    def refresh(self):
        rows = self.win.db.cards(self.deck.currentData() or None, self.search.text().strip())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        t = today()
        for r, c in enumerate(rows):
            vals = [c["word"], c["ipa"], c["uz"], c["ru"]]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 1:
                    it.setFont(QFont("Segoe UI", 10))
                if j == 0:
                    it.setData(Qt.UserRole, c["id"])
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(r, j, it)
            if c["seen"] and c["due"]:
                dd = date.fromisoformat(c["due"])
                due = QTableWidgetItem(dd.strftime("%d.%m.%Y"))
                if dd <= t:
                    due.setForeground(QColor("#e8590c"))
            else:
                due = QTableWidgetItem(tr("c_new"))
                due.setForeground(QColor("#1c7ed6"))
            self.table.setItem(r, 4, due)
            self.table.setItem(r, 5, QTableWidgetItem(c["deck_name"]))
        self.table.setSortingEnabled(True)
        self.count.setText(tr("n_cards", n=len(rows)))

    def _sel(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 0)
            if it:
                ids.append(it.data(Qt.UserRole))
        return ids

    def edit(self):
        ids = self._sel()
        if ids:
            self.win.edit_card(ids[0])

    def delete(self):
        ids = self._sel()
        if ids and ask(self, tr("confirm_delete_cards", n=len(ids))):
            for i in ids:
                self.win.db.delete_card(i)
            self.win.data_changed()

    def speak(self):
        ids = self._sel()
        if ids:
            c = self.win.db.card(ids[0])
            self.win.speaker.speak(c["word"])

    def _menu(self, pos):
        ids = self._sel()
        if not ids:
            return
        m = QMenu(self)
        m.addAction(tr("pronounce"), self.speak)
        m.addAction(tr("edit"), self.edit)
        mv = m.addMenu(tr("move_to"))
        for d in self.win.db.decks():
            mv.addAction(d["name"], lambda did=d["id"]: self._move(ids, did))
        m.addAction(tr("reset_progress"), lambda: self._reset(ids))
        m.addSeparator()
        m.addAction(tr("delete"), self.delete)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _move(self, ids, did):
        for i in ids:
            self.win.db.update_card(i, deck_id=did)
        self.win.data_changed()

    def _reset(self, ids):
        for i in ids:
            self.win.db.reset_card(i)
        self.win.data_changed()


# =========================================================================== statistika
class StatTile(QFrame):
    def __init__(self, icon_name, title, color):
        super().__init__()
        self.setObjectName("StatTile")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        ic = QLabel()
        ic.setPixmap(icon(icon_name, color, 26).pixmap(26, 26))
        h.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.v = QLabel("0")
        self.v.setStyleSheet(f"font-size: 18pt; font-weight: 700; color: {color};")
        t = QLabel(title)
        t.setObjectName("Muted")
        col.addWidget(self.v)
        col.addWidget(t)
        h.addLayout(col, 1)


class StatsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.t_streak = StatTile("flame", tr("s_streak"), "#e8590c")
        self.t_today = StatTile("target", tr("s_today"), accent())
        self.t_acc = StatTile("check", tr("s_accuracy"), "#2f9e44")
        self.t_total = StatTile("cards", tr("s_cards"), "#1c7ed6")
        for t in (self.t_streak, self.t_today, self.t_acc, self.t_total):
            row.addWidget(t, 1)
        lay.addLayout(row)
        c1 = Card(tr("chart_30"))
        self.bars = BarChart()
        self.bars.setMinimumHeight(200)
        c1.add(self.bars)
        lay.addWidget(c1, 3)
        r2 = QHBoxLayout()
        r2.setSpacing(12)
        c2 = Card(tr("chart_states"))
        self.donut = DonutChart()
        c2.add(self.donut)
        c3 = Card(tr("chart_forecast"))
        self.fc = BarChart()
        c3.add(self.fc)
        r2.addWidget(c2, 1)
        r2.addWidget(c3, 1)
        lay.addLayout(r2, 2)

    def refresh(self):
        db, t = self.win.db, today()
        goal = self.win.goal()
        met = db.days_meeting_goal(goal)
        self.t_streak.v.setText(tr("n_days", n=srs.streak(met, t)))
        self.t_streak.setToolTip(tr("best_streak", n=srs.best_streak(met)))
        per = db.reviews_per_day(t - timedelta(days=29), t)
        self.t_today.v.setText(f"{per.get(t, 0)} / {goal}")
        acc = db.accuracy(t - timedelta(days=29))
        self.t_acc.v.setText("—" if acc is None else f"{round(acc * 100)}%")
        cats = db.categories()
        self.t_total.v.setText(str(sum(cats.values())))
        days = [t - timedelta(days=29 - i) for i in range(30)]
        labels = [d.strftime("%d.%m") if i % 5 == 4 or i == 29 else "" for i, d in enumerate(days)]
        self.bars.set_data(labels, [(tr("reviews"), accent(), [per.get(d, 0) for d in days])])
        self.donut.set_data([(tr("st_new"), cats["new"], "#1c7ed6"), (tr("st_learning"), cats["learning"], "#e8590c"),
                             (tr("st_mature"), cats["mature"], "#2f9e44")], str(sum(cats.values())), tr("s_cards"))
        f = db.forecast(t, 7)
        fl = [tr("today_short") if i == 0 else (t + timedelta(days=i)).strftime("%d.%m") for i in range(7)]
        self.fc.set_data(fl, [(tr("due_cards"), "#7048e8", f)], show_values=True)


# =========================================================================== sozlamalar
class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        s = win.settings
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.addWidget(header(tr("settings_title"), tr("settings_sub")))
        g = Card(tr("daily"))
        f = QFormLayout()
        self.goal = QSpinBox()
        self.goal.setRange(5, 500)
        self.goal.setValue(win.goal())
        self.goal.valueChanged.connect(lambda v: self._set("goal", v))
        self.newl = QSpinBox()
        self.newl.setRange(0, 200)
        self.newl.setValue(win.new_limit())
        self.newl.valueChanged.connect(lambda v: self._set("new_per_day", v))
        f.addRow(tr("goal_reviews"), self.goal)
        f.addRow(tr("new_per_day"), self.newl)
        g.add(f)
        lay.addWidget(g)
        v = Card(tr("voice_title"))
        if win.speaker.available:
            f2 = QFormLayout()
            self.voice = QComboBox()
            self.voice.addItems(win.speaker.voices())
            cur = s.get("voice") if isinstance(s.get("voice"), str) else ""
            cur = cur or win.speaker.default_voice()
            self.voice.setCurrentIndex(max(0, self.voice.findText(cur)))
            self.voice.currentTextChanged.connect(self._voice)
            self.rate = QSlider(Qt.Horizontal)
            self.rate.setRange(-5, 5)
            self.rate.setValue(win._int_setting("rate", -1, -5, 5))
            self.rate.valueChanged.connect(self._rate)
            f2.addRow(tr("voice"), self.voice)
            f2.addRow(tr("rate"), self.rate)
            v.add(f2)
            r = QHBoxLayout()
            tb = icon_button("speaker", tr("test_voice"), tr("test_voice"))
            tb.clicked.connect(lambda: win.speaker.speak("Hello! This is a pronunciation test."))
            r.addWidget(tb)
            r.addStretch(1)
            v.add(r)
            if not any(win.speaker.is_english(l) for _, l, _ in win.speaker._voices):
                h = QLabel(tr("no_english_voice"))
                h.setObjectName("Muted")
                h.setWordWrap(True)
                v.add(h)
        else:
            h = QLabel(tr("no_sapi"))
            h.setObjectName("Muted")
            h.setWordWrap(True)
            v.add(h)
        self.auto = QCheckBox(tr("auto_speak"))
        self.auto.setChecked(bool(s.get("auto_speak", True)))
        self.auto.toggled.connect(lambda val: self._set("auto_speak", val))
        v.add(self.auto)
        lay.addWidget(v)
        d = Card(tr("data"))
        p = QLabel(str(win.db.path))
        p.setObjectName("Muted")
        p.setWordWrap(True)
        p.setTextInteractionFlags(Qt.TextSelectableByMouse)
        d.add(p)
        r2 = QHBoxLayout()
        ob = icon_button("folder", tr("open_data_folder"), tr("open_data_folder"))
        ob.clicked.connect(lambda: open_path(str(win.db.path.parent)))
        r2.addWidget(ob)
        r2.addStretch(1)
        d.add(r2)
        lay.addWidget(d)
        lay.addStretch(1)

    def _set(self, k, v):
        if not is_demo():
            self.win.settings.set(k, v)
        self.win.data_changed()

    def _voice(self, name):
        self.win.speaker.select(name)
        if not is_demo():
            self.win.settings.set("voice", name)

    def _rate(self, v):
        self.win.speaker.set_rate(v)
        if not is_demo():
            self.win.settings.set("rate", v)


# =========================================================================== demo
def load_demo(db: DB, win):
    rnd = random.Random(7)
    t = today()
    for key in cardio.BUILTIN_DECKS:
        win.add_builtin(key, quiet=True)
    cards = db.cards()
    for c in cards[:420]:
        if rnd.random() < 0.55:
            reps = rnd.randint(1, 6)
            interval = rnd.choice([1, 2, 4, 6, 9, 15, 24, 33, 48])
            due = t + timedelta(days=rnd.randint(-1, 9))
            db.con.execute("UPDATE cards SET reps=?, interval=?, ef=?, due=?, seen=1 WHERE id=?",
                           (reps, interval, round(rnd.uniform(1.8, 2.8), 2), due.isoformat(), c["id"]))
    ids = [c["id"] for c in cards]
    for back in range(40, -1, -1):
        d = t - timedelta(days=back)
        if back in (17, 23, 31):
            continue
        n = rnd.randint(14, 46) if back else 13
        for _ in range(n):
            db.con.execute("INSERT INTO reviews(card_id, ts, day, grade, mode, was_new) VALUES(?,?,?,?,?,0)",
                           (rnd.choice(ids), f"{d.isoformat()}T19:00:00", d.isoformat(),
                            rnd.choices([1, 2, 3, 4], [12, 18, 55, 15])[0], "flip"))
    db.con.commit()


# =========================================================================== asosiy oyna
class RailButton(QToolButton):
    def __init__(self, text, icon_name):
        super().__init__()
        self.icon_name = icon_name
        self.setText(text)
        self.setCheckable(True)
        self.setObjectName("Rail")
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(24, 24))
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(66)
        self.recolor()

    def recolor(self):
        self.setIcon(icon(self.icon_name, accent() if self.isChecked() else pal()["muted"], 24))


class PageCount:
    """BaseMainWindow._nav o'rnida: tekshiruv vositalari sahifalar sonini bilishi uchun."""

    def __init__(self, stack):
        self.stack = stack

    def count(self):
        return self.stack.count()


class MainWindow(BaseMainWindow):
    def __init__(self):
        super().__init__()
        self.data_dir = app_data_dir(SLUG)
        self.db = DB(self.data_dir / "kartalar.db")
        self.speaker = Speaker()
        if self.speaker.available:
            if isinstance(self.settings.get("voice"), str):
                self.speaker.select(self.settings.get("voice"))
            self.speaker.set_rate(self._int_setting("rate", -1, -5, 5))
        first_run = not self.db.decks() and not self.db.get_meta("initialized")
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("RailBar")
        rail.setFixedWidth(96)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(6, 12, 6, 12)
        rl.setSpacing(4)
        self.nav = QButtonGroup(self)
        self.rail_btns = []
        for i, (key, ic) in enumerate((("page_home", "home"), ("page_study", "cards"), ("page_cards", "list"),
                                       ("page_stats", "chart"), ("page_settings", "gear"))):
            b = RailButton(tr(key), ic)
            self.nav.addButton(b, i)
            self.rail_btns.append(b)
            rl.addWidget(b)
        rl.addStretch(1)
        h.addWidget(rail)
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.home = HomePage(self)
        self.study = StudyPage(self)
        self.cards = CardsPage(self)
        self.stats = StatsPage(self)
        self.settings_page = SettingsPage(self)
        for w in (self.home, self.study, self.cards, self.stats, self.settings_page):
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(24, 18, 24, 16)
            hl.addWidget(w)
            self.stack.addWidget(holder)
        self.nav.idClicked.connect(self.set_page)
        self._nav = PageCount(self.stack)   # uzkit/verify: sahifalar soni

        a = QAction(tr("add_card"), self)
        a.setShortcut("Ctrl+N")
        a.triggered.connect(lambda: self.add_card(None))
        a2 = QAction(tr("import_file"), self)
        a2.setShortcut("Ctrl+I")
        a2.triggered.connect(self.import_file)
        first = self.menu_file.actions()[0]
        self.menu_file.insertAction(first, a)
        self.menu_file.insertAction(first, a2)
        self.menu_file.insertSeparator(first)

        if is_demo():
            if not self.db.get_meta("demo"):
                load_demo(self.db, self)
                self.db.set_meta("demo", "1")
        elif first_run:
            for key in cardio.BUILTIN_DECKS:
                self.add_builtin(key, quiet=True)
            self.db.set_meta("initialized", "1")
        self.study.fill_decks()
        self.cards.fill_decks()
        self.data_changed()
        self.study.load_queue()
        self.set_page(0)
        if is_demo():
            QTimer.singleShot(0, self._demo_reveal)

    def _demo_reveal(self):
        if self.study.card:
            self.study.reveal()

    # ------------------------------------------------------------------ umumiy
    def set_page(self, i):
        if not 0 <= i < self.stack.count():
            return
        self.stack.setCurrentIndex(i)
        self.nav.button(i).setChecked(True)
        for b in self.rail_btns:
            b.recolor()
        if i == 1 and self.study.pos >= len(self.study.queue):
            self.study.load_queue()
        if i == 3:
            self.stats.refresh()

    def _int_setting(self, key, default, lo, hi):
        v = self.settings.get(key, default)
        return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else default

    def goal(self):
        return self._int_setting("goal", 20, 5, 500)

    def new_limit(self):
        return self._int_setting("new_per_day", 10, 0, 200)

    def data_changed(self):
        self.home.refresh()
        self.cards.refresh()
        if self.stack.currentIndex() == 3:
            self.stats.refresh()

    def decks_changed(self, select=None):
        self.study.fill_decks()
        self.cards.fill_decks(select)
        self.data_changed()

    def on_theme_changed(self):
        from .ui_extra import _ICON_CACHE
        _ICON_CACHE.clear()
        for b in self.rail_btns:
            b.recolor()
        self.data_changed()
        self.stats.refresh()
        self.study._update_progress()

    # ------------------------------------------------------------------ to'plamlar
    def add_builtin(self, key, quiet=False):
        d = cardio.BUILTIN_DECKS[key]
        try:
            rows = cardio.load_builtin(resource("assets", "decks"), key)
        except Exception as ex:
            appmod.log_exception(ex)
            if not quiet:
                error(self, tr("builtin_error"))
            return
        existing = self.db.deck_by_builtin(key)
        if existing:
            n = self.db.add_cards(existing["id"], rows)
            if not quiet:
                info(self, tr("builtin_updated", n=n))
            did = existing["id"]
        else:
            did = self.db.add_deck(d["name"][language()], key)
            self.db.add_cards(did, rows)
        if not quiet:
            self.decks_changed()

    def new_deck(self):
        name, ok = QInputDialog.getText(self, tr("new_deck"), tr("deck_name"))
        if ok and name.strip():
            did = self.db.add_deck(name.strip())
            self.decks_changed(did)

    def rename_deck(self, did):
        d = self.db.deck(did)
        name, ok = QInputDialog.getText(self, tr("rename"), tr("deck_name"), text=d["name"])
        if ok and name.strip():
            self.db.rename_deck(did, name.strip())
            self.decks_changed()

    def delete_deck(self, did):
        d = self.db.deck(did)
        n = self.db.deck_counts(did, today())["total"]
        if ask(self, tr("confirm_delete_deck", name=d["name"], n=n)):
            self.db.delete_deck(did)
            self.decks_changed()

    def start_study(self, did):
        self.study.fill_decks(did or 0)
        self.study.load_queue()
        self.set_page(1)

    def show_cards(self, did):
        self.cards.fill_decks(did)
        self.cards.refresh()
        self.set_page(2)

    # ------------------------------------------------------------------ kartalar
    def _store_image(self, cid, path):
        if not path:
            return ""
        p = Path(path)
        img_dir = self.data_dir / "images"
        if p.is_file() and img_dir not in p.parents:
            img_dir.mkdir(exist_ok=True)
            dst = img_dir / f"{cid}_{p.name}"
            shutil.copy2(p, dst)
            return str(dst)
        return path

    def add_card(self, did=None):
        if not self.db.decks():
            self.db.add_deck(tr("my_deck"))
            self.decks_changed()
        dlg = CardDialog(self, None, did)
        if dlg.exec():
            v = dlg.values()
            cid = self.db.add_card(v["deck_id"], v["word"], v["ipa"], v["uz"], v["ru"], v["example"])
            if v["image"]:
                self.db.update_card(cid, image=self._store_image(cid, v["image"]))
            self.data_changed()
            self.status(tr("card_added"))

    def edit_card(self, cid):
        c = self.db.card(cid)
        if not c:
            return
        dlg = CardDialog(self, c)
        if dlg.exec():
            v = dlg.values()
            v["image"] = self._store_image(cid, v["image"]) if v["image"] != c["image"] else v["image"]
            self.db.update_card(cid, **v)
            self.data_changed()

    # ------------------------------------------------------------------ import / eksport
    def import_file(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("import_file"), str(Path.home()),
                                           tr("tables") + " (*.csv *.xlsx *.tsv *.txt)")
        if not p:
            return
        try:
            rows = cardio.read_table(p)
        except Exception as ex:
            appmod.log_exception(ex)
            error(self, tr("import_error"))
            return
        if not rows:
            warn(self, tr("import_empty"))
            return
        dlg = ImportDialog(self, rows, Path(p).stem)
        if not dlg.exec():
            return
        data = cardio.apply_mapping(rows, dlg.mapping(), dlg.header_cb.isChecked())
        did = dlg.deck.currentData() or self.db.add_deck(Path(p).stem)
        n = self.db.add_cards(did, data)
        self.decks_changed(did)
        info(self, tr("imported_n", n=n, skipped=len(data) - n))

    def export_deck(self, did, fmt):
        name = self.db.deck(did)["name"] if did else tr("all_decks")
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip() or "cards"
        ext = {"csv": "csv", "xlsx": "xlsx", "tsv": "txt"}[fmt]
        flt = {"csv": "CSV (*.csv)", "xlsx": "Excel (*.xlsx)", "tsv": "Anki TSV (*.txt *.tsv)"}[fmt]
        p, _ = QFileDialog.getSaveFileName(self, tr("export"), str(Path.home() / f"{safe}.{ext}"), flt)
        if not p:
            return
        cards = self.db.cards(did)
        rows = cardio.export_rows(cards)
        heads = [tr("f_word"), tr("f_ipa"), tr("f_uz"), tr("f_ru"), tr("f_example")]
        try:
            if fmt == "csv":
                cardio.write_csv(p, ["word", "ipa", "uz", "ru", "example"], rows)
            elif fmt == "xlsx":
                write_xlsx(p, name[:31], heads, rows, widths=[22, 20, 30, 30, 60], title=name)
            else:
                cardio.write_tsv(p, rows)
            self.status(tr("saved_to", path=p))
        except Exception as ex:
            appmod.log_exception(ex)
            error(self, tr("export_error"))
