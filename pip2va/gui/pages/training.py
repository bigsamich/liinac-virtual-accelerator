"""Training page: run fault scenarios, get scored on recovery."""
from __future__ import annotations

import time

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QPushButton,
                             QTextEdit, QVBoxLayout)


class DebriefWorker(QThread):
    done = pyqtSignal(str, str)

    def __init__(self, r, st):
        super().__init__()
        self.r, self.st = r, st

    def run(self):
        text, engine = scenarios.llm_debrief(self.r, self.st)
        self.done.emit(text, engine)

from pip2va.analysis import scenarios

from .. import theme
from . import register
from .common import Page


@register("Training")
class TrainingPage(Page):
    title = "Operator Training — Fault Scenarios"

    def build(self):
        lay = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Scenario:"))
        self.lst = QListWidget()
        self.lst.addItems(scenarios.SCENARIOS.keys())
        self.lst.setCurrentRow(0)
        left.addWidget(self.lst, 1)
        self.btn_start = QPushButton("START scenario")
        self.btn_start.setObjectName("danger")
        left.addWidget(self.btn_start)
        self.btn_debrief = QPushButton("AI instructor debrief")
        left.addWidget(self.btn_debrief)
        self.lbl_engine = QLabel("")
        self.lbl_engine.setStyleSheet("color:#8b96a5;")
        left.addWidget(self.lbl_engine)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        right.addWidget(self.txt, 1)
        self.lbl_clock = QLabel("—")
        self.lbl_clock.setStyleSheet(
            f"font-size:22px; font-weight:bold; color:{theme.ACCENT};")
        right.addWidget(self.lbl_clock)
        lay.addLayout(right, 2)
        self.body.addLayout(lay, 1)

        self._reviewed = True
        self.lst.currentTextChanged.connect(self._show)
        self.btn_start.clicked.connect(self._start)
        self.btn_debrief.clicked.connect(self._debrief)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(1000)
        self._show(self.lst.currentItem().text())

    def _show(self, name):
        sc = scenarios.SCENARIOS.get(name)
        if sc:
            self.txt.setPlainText(
                f"{name}\n\n{sc['desc']}\n\nPar time: {sc['par']:.0f} s\n\n"
                "Recovery counts when: all injected faults cleared, tripped "
                "devices reset, beam permit restored, transmission > 99 %.\n"
                "Use the MPS Fault Analysis tab — the clock is running.")

    def _start(self):
        name = self.lst.currentItem().text()
        scenarios.start(self.hub.r, self.hub.inject_fault,
                        self.hub.set_setting, name)
        self._reviewed = False
        self._show(name)

    def _debrief(self):
        st = {k.decode(): v.decode()
              for k, v in self.hub.r.hgetall("state:training").items()}
        if not st:
            return
        self.lbl_engine.setText("instructor thinking…")
        self._dw = DebriefWorker(self.hub.r, st)
        self._dw.done.connect(lambda t, e: (
            self.txt.setPlainText(t), self.lbl_engine.setText(f"engine: {e}")))
        self._dw.start()

    def _poll(self):
        if not self.isVisible():
            return
        st = scenarios.check(self.hub.r)
        if not st:
            return
        if st.get("active") == "1":
            el = time.time() - float(st["t0"])
            self.lbl_clock.setText(f"⏱ {st.get('scenario', '')}: {el:.0f} s")
        elif float(st.get("score", -1)) >= 0:
            sc = scenarios.SCENARIOS.get(st.get("scenario", ""), {})
            g = scenarios.grade(float(st["score"]), sc.get("par", 60.0))
            self.lbl_clock.setText(
                f"✔ {st.get('scenario', '')}: recovered in "
                f"{float(st['score']):.0f} s — {g}")
            if not getattr(self, "_reviewed", True):
                self._reviewed = True
                self.txt.setPlainText(scenarios.review(self.hub.r, st))
                self.lbl_engine.setText(
                    "review ready — click AI instructor debrief for critique")
