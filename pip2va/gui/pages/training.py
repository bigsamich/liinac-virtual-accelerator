"""Training page: run fault scenarios, get scored on recovery."""
from __future__ import annotations

import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QPushButton,
                             QTextEdit, QVBoxLayout)

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

        self.lst.currentTextChanged.connect(self._show)
        self.btn_start.clicked.connect(self._start)
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
        scenarios.start(self.hub.r, self.hub.inject_fault, name)
        self._show(name)

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
