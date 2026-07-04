"""Strip tool: trend any machine channel vs time."""
from __future__ import annotations

import collections
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget,
                             QPushButton, QVBoxLayout)

from ..plotkit import CrosshairPlot, short_label
from . import register
from .common import Page

COLORS = ["#4fc3f7", "#ffb74d", "#ba68c8", "#4db6ac", "#e57373",
          "#aed581", "#f06292", "#90a4ae"]
MAXLEN = 1200   # one minute at 20 Hz
MAX_CH = 8


@register("Strip Tool")
class StripToolPage(Page):
    title = "Strip Tool — trend any channel"

    def build(self):
        lat = self.lat
        # channel catalog: (label, source, index/field)
        self.catalog: dict[str, tuple] = {
            "beam:W_out [MeV]": ("state", "w_out"),
            "beam:transmission": ("state", "transmission"),
            "beam:I_out [mA]": ("state", "i_out_ma"),
            "beam:lag [ms]": ("state", "lag_ms"),
        }
        for k, e in enumerate(lat.instruments("toroid")):
            self.catalog[f"{short_label(e.name)} [mA]"] = ("toroids", k)
        for k, e in enumerate(lat.instruments("bpm")):
            n = short_label(e.name)
            self.catalog[f"{n}:x [mm]"] = ("orbit.x", k)
            self.catalog[f"{n}:y [mm]"] = ("orbit.y", k)
            self.catalog[f"{n}:phase [deg]"] = ("orbit.phase", k)
        for k, e in enumerate(lat.instruments("blm")):
            self.catalog[f"{short_label(e.name)} [W/m]"] = ("losses", k)
        rf_index = None  # resolved lazily from the hub
        self._rf_names: list[str] = []
        for e in lat.elements:
            if e.type in ("rfgap", "rfq"):
                n = short_label(e.name)
                self.catalog[f"{n}:amp [MV]"] = ("rf.amp", e.name)
                self.catalog[f"{n}:det [Hz]"] = ("rf.detuning_hz", e.name)

        bar = QHBoxLayout()
        self.sel = QComboBox()
        self.sel.setEditable(True)          # searchable
        self.sel.addItems(sorted(self.catalog))
        self.btn_add = QPushButton("Add")
        self.btn_clear = QPushButton("Clear all")
        bar.addWidget(self.sel, 1)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_clear)
        self.body.addLayout(bar)

        body = QHBoxLayout()
        self.lst = QListWidget()
        self.lst.setFixedWidth(230)
        body.addWidget(self.lst)
        self.plot = CrosshairPlot("value", xlabel="time [s]")
        self.plot.addLegend(offset=(6, 6), labelTextSize="8pt")
        body.addWidget(self.plot, 1)
        self.body.addLayout(body, 1)

        self.active: dict[str, dict] = {}   # label -> {buf, tbuf, curve}
        self._rf_pos: dict[str, int] | None = None
        self._t0 = time.monotonic()
        self._draw = 0

        self.btn_add.clicked.connect(self._add)
        self.btn_clear.clicked.connect(self._clear)
        self.lst.itemDoubleClicked.connect(
            lambda it: self._remove(it.text()))
        self.hub.beamState.connect(lambda st: self._feed("state", st))
        self.hub.toroids.connect(lambda _p, d: self._feed("toroids", d))
        self.hub.orbit.connect(lambda _p, d: self._feed("orbit", d))
        self.hub.losses.connect(lambda _p, d: self._feed("losses", d))
        self.hub.rf.connect(lambda _p, d: self._feed("rf", d))

    # -------------------------------------------------------------- channels

    def _add(self):
        label = self.sel.currentText()
        if label not in self.catalog or label in self.active \
                or len(self.active) >= MAX_CH:
            return
        curve = self.plot.plot(
            pen=pg.mkPen(COLORS[len(self.active) % len(COLORS)], width=1.4),
            name=label)
        self.active[label] = {
            "buf": collections.deque(maxlen=MAXLEN),
            "t": collections.deque(maxlen=MAXLEN), "curve": curve}
        self.lst.addItem(label)

    def _remove(self, label: str):
        ch = self.active.pop(label, None)
        if ch:
            self.plot.pw.removeItem(ch["curve"])
        for i in range(self.lst.count()):
            if self.lst.item(i).text() == label:
                self.lst.takeItem(i)
                break

    def _clear(self):
        for label in list(self.active):
            self._remove(label)

    # ------------------------------------------------------------------ data

    def _feed(self, source: str, data):
        now = time.monotonic() - self._t0
        for label, ch in self.active.items():
            src, key = self.catalog[label]
            val = self._extract(src, key, source, data)
            if val is not None:
                ch["t"].append(now)
                ch["buf"].append(val)
        self._draw += 1
        if not self.isVisible() or self._draw % 4:
            return
        allv = []
        for ch in self.active.values():
            if ch["buf"]:
                ch["curve"].setData(np.fromiter(ch["t"], float),
                                    np.fromiter(ch["buf"], float))
                allv.append(np.fromiter(ch["buf"], float))
        if allv:
            self.plot.update_y(*allv)

    def _extract(self, src, key, source, data):
        try:
            if source == "state" and src == "state":
                return float(data.get(key)) if data.get(key) is not None else None
            if source == "toroids" and src == "toroids":
                return float(data["i_ma"][key])
            if source == "orbit" and src.startswith("orbit."):
                f = src.split(".")[1]
                v = float(data[f][key])
                return v * 1e3 if f in ("x", "y") else v
            if source == "losses" and src == "losses":
                return float(data["wpm"][key])
            if source == "rf" and src.startswith("rf."):
                if self._rf_pos is None:
                    idx = self.hub.get_index("rf")
                    self._rf_pos = {n: j for j, n in enumerate(idx)} if idx \
                        else None
                if not self._rf_pos:
                    return None
                j = self._rf_pos.get(key)
                f = src.split(".", 1)[1]
                return float(data[f][j]) if j is not None else None
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        return None
