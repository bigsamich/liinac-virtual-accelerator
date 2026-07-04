"""RF tuner & viewer: per-cavity table with a detail pane."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem)

from .. import theme
from . import register
from .common import Page, make_plot


@register("RF")
class RfPage(Page):
    title = "RF Systems"

    def build(self):
        self.cavs = [e for e in self.lat.elements
                     if e.type in ("rfgap", "rfq")]
        bar = QHBoxLayout()
        self.sec = QComboBox()
        self.sec.addItem("ALL")
        for s in self.lat.sections:
            if any(c.section == s.name for c in self.cavs):
                self.sec.addItem(s.name)
        bar.addWidget(QLabel("Section:"))
        bar.addWidget(self.sec)
        bar.addStretch(1)
        self.body.addLayout(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Cavity", "Amp set [MV]", "Phase set [deg]", "Amp rb", "Phase rb",
             "Detune [Hz]", "Fwd [norm]", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.body.addWidget(self.table, 2)

        # detail pane
        det_bar = QHBoxLayout()
        self.lbl_sel = QLabel("select a cavity…")
        self.btn_reset = QPushButton("Reset trip")
        det_bar.addWidget(self.lbl_sel)
        det_bar.addStretch(1)
        det_bar.addWidget(self.btn_reset)
        self.body.addLayout(det_bar)
        self.p_det = make_plot("detuning [Hz]", xlabel="pulse")
        self.c_det = self.p_det.plot(pen=pg.mkPen(theme.ACCENT, width=1.5))
        self.body.addWidget(self.p_det, 1)

        self._index: list[str] | None = None
        self._hist: dict[str, collections.deque] = {}
        self._visible: list[int] = []
        self._items: dict[int, dict] = {}
        self._sel: str | None = None

        self.sec.currentTextChanged.connect(self._rebuild)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.btn_reset.clicked.connect(self._reset_sel)
        self.hub.rf.connect(self._on_rf)
        self._rebuild()

    def _rebuild(self, *_):
        sec = self.sec.currentText()
        self.table.setRowCount(0)
        self._visible = []
        self._items.clear()
        for i, el in enumerate(self.cavs):
            if sec != "ALL" and el.section != sec:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(el.name))
            st = self.hub.get_settings("rf", el.name)
            p = el.params
            amp = QDoubleSpinBox()
            qlim = p.get("quench_mv", 1.3 * p.get("v_mv", p.get("v_design", 1.0)))
            amp.setRange(0.0, qlim * 1.2)
            amp.setToolTip(f"quench limit {qlim:g} MV")
            amp.setDecimals(3)
            amp.setSingleStep(0.05)
            amp.setValue(float(st.get("amp", p.get("v_mv", p.get("v_design", 1.0)))))
            amp.valueChanged.connect(
                lambda v, el=el: self.hub.set_setting("rf", el.name, "amp", v))
            self.table.setCellWidget(r, 1, amp)
            ph = QDoubleSpinBox()
            ph.setRange(-180.0, 180.0)
            ph.setDecimals(2)
            ph.setValue(float(st.get("phase", p.get("phi_deg", 0.0))))
            ph.valueChanged.connect(
                lambda v, el=el: self.hub.set_setting("rf", el.name, "phase", v))
            self.table.setCellWidget(r, 2, ph)
            cells = {}
            for col, key in ((3, "amp"), (4, "phase"), (5, "det"),
                             (6, "fwd"), (7, "status")):
                it = QTableWidgetItem("—")
                it.setFlags(Qt.ItemFlag.ItemIsEnabled |
                            Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, col, it)
                cells[key] = it
            self._items[i] = cells
            self._visible.append(i)

    def _on_select(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._visible):
            self._sel = self.cavs[self._visible[row]].name
            self.lbl_sel.setText(f"detail: {self._sel}")

    def _reset_sel(self):
        if self._sel:
            self.hub.set_setting("rf", self._sel, "reset", 1)

    def _on_rf(self, _pid, data):
        if self._index is None:
            idx = self.hub.get_index("rf")
            self._index = idx or None
        if not self._index:
            return
        pos = {n: j for j, n in enumerate(self._index)}
        for i in self._visible:
            el = self.cavs[i]
            j = pos.get(el.name)
            if j is None or j >= len(data["amp"]):
                continue
            c = self._items[i]
            c["amp"].setText(f'{data["amp"][j]:.3f}')
            c["phase"].setText(f'{data["phase"][j]:.2f}')
            c["det"].setText(f'{data["detuning_hz"][j]:+.1f}')
            c["fwd"].setText(f'{data["forward_pw"][j]:.2f}')
            tripped = data["status"][j] > 0.5
            c["status"].setText("TRIPPED" if tripped else "ok")
            from PyQt6.QtGui import QBrush, QColor
            c["status"].setForeground(
                QBrush(QColor(theme.ALARM if tripped else theme.OK)))
        # detail history
        for n, j in pos.items():
            if j < len(data["detuning_hz"]):
                self._hist.setdefault(
                    n, collections.deque(maxlen=400)).append(
                        float(data["detuning_hz"][j]))
        if self._sel and self._sel in self._hist:
            h = self._hist[self._sel]
            self.c_det.setData(np.arange(len(h)), np.fromiter(h, float))
