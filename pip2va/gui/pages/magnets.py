"""Magnet & trim control: setpoints vs readbacks for every magnet."""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem)

from .. import theme
from . import register
from .common import Page

FIELDS = {"solenoid": ["current"], "quad": ["current"],
          "corrector": ["current_x", "current_y"]}


@register("Magnets")
class MagnetsPage(Page):
    title = "Magnets & Trims"

    def build(self):
        bar = QHBoxLayout()
        self.sec = QComboBox()
        self.sec.addItem("ALL")
        for s in self.lat.sections:
            self.sec.addItem(s.name)
        self.search = QLineEdit()
        self.search.setPlaceholderText("filter by name…")
        self.btn_zero = QPushButton("Zero all correctors")
        bar.addWidget(QLabel("Section:"))
        bar.addWidget(self.sec)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.btn_zero)
        self.body.addLayout(bar)

        self.rows = []   # (el, field, index_key)
        for el in self.lat.elements:
            for f in FIELDS.get(el.type, []):
                self.rows.append((el, f, f"{el.name}:{f}"))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Element", "Type", "Field", "Setpoint [A]", "Readback [A]",
             "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.body.addWidget(self.table, 1)

        self.sec.currentTextChanged.connect(self._rebuild)
        self.search.textChanged.connect(self._rebuild)
        self.btn_zero.clicked.connect(self._zero_correctors)
        self.hub.magnets.connect(self._on_magnets)
        self._index = None
        self._visible: list[int] = []
        self._rb_items: dict[int, QTableWidgetItem] = {}
        self._st_items: dict[int, QTableWidgetItem] = {}
        self._rebuild()

    # ------------------------------------------------------------- table

    def _rebuild(self, *_):
        sec = self.sec.currentText()
        pat = self.search.text().upper()
        self.table.setRowCount(0)
        self._visible = []
        self._rb_items.clear()
        self._st_items.clear()
        for i, (el, f, _key) in enumerate(self.rows):
            if sec != "ALL" and el.section != sec:
                continue
            if pat and pat not in el.name.upper():
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(el.name))
            self.table.setItem(r, 1, QTableWidgetItem(el.type))
            self.table.setItem(r, 2, QTableWidgetItem(f))
            spin = QDoubleSpinBox()
            lim = (el.params.get("max_amp", 10.0) if el.type == "corrector"
                   else el.params.get("max_current", 2000.0))
            spin.setRange(-lim, lim)
            spin.setToolTip(f"supply limit ±{lim:g} A")
            spin.setDecimals(3)
            st = self.hub.get_settings("magnet", el.name)
            spin.setValue(float(st.get(f, el.params.get("design_current", 0.0)
                                       if el.type != "corrector" else 0.0)))
            spin.valueChanged.connect(
                lambda v, el=el, f=f: self.hub.set_setting(
                    "magnet", el.name, f, v))
            self.table.setCellWidget(r, 3, spin)
            rb = QTableWidgetItem("—")
            rb.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 4, rb)
            stat = QTableWidgetItem("—")
            stat.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 5, stat)
            self._rb_items[i] = rb
            self._st_items[i] = stat
            self._visible.append(i)

    def _zero_correctors(self):
        for el, f, _ in self.rows:
            if el.type == "corrector":
                self.hub.set_setting("magnet", el.name, f, 0.0)
        self._rebuild()

    def _on_magnets(self, _pid, data):
        if self._index is None:
            idx = self.hub.get_index("magnet")
            self._index = {k: j for j, k in enumerate(idx)} if idx else None
        if not self._index:
            return
        vals, stats = data["values"], data["status"]
        for i in self._visible:
            _el, _f, key = self.rows[i]
            j = self._index.get(key)
            if j is None or j >= len(vals):
                continue
            self._rb_items[i].setText(f"{vals[j]:.3f}")
            tripped = stats[j] > 0.5
            self._st_items[i].setText("TRIPPED" if tripped else "ok")
            self._st_items[i].setForeground(
                pg_color(theme.ALARM if tripped else theme.OK))


def pg_color(c):
    from PyQt6.QtGui import QBrush, QColor
    return QBrush(QColor(c))
