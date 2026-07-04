"""Intra-pulse waveform viewer: live toroids, selectable captures, postmortem."""
from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget,
                             QPushButton, QVBoxLayout)

from .. import theme
from . import register
from .common import Page, make_plot

COLORS = [theme.ACCENT, "#ffb74d", "#ba68c8", "#4db6ac", "#e57373",
          "#aed581", "#f06292", "#90a4ae"]


@register("Waveforms")
class WaveformsPage(Page):
    title = "Intra-Pulse Waveforms (1000 samples / 0.55 ms)"

    def build(self):
        lat = self.lat

        # ---- live toroid waveform
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Toroid:"))
        self.sel_tor = QComboBox()
        self.sel_tor.addItems([e.name for e in lat.instruments("toroid")])
        self.sel_tor.setCurrentIndex(self.sel_tor.count() - 1)
        bar.addWidget(self.sel_tor)
        bar.addStretch(1)
        self.body.addLayout(bar)
        self.p_tor = make_plot("I [mA]", xlabel="t in pulse [ms]")
        self.c_tor = self.p_tor.plot(pen=pg.mkPen(theme.ACCENT, width=1.5))
        self.body.addWidget(self.p_tor, 2)

        # ---- selectable capture
        cap = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Capture devices (up to 8):"))
        self.sel_cls = QComboBox()
        self.sel_cls.addItems(["bpm", "blm", "toroid"])
        self.sel_dev = QComboBox()
        self.btn_add = QPushButton("Add")
        self.btn_clear = QPushButton("Clear")
        row = QHBoxLayout()
        row.addWidget(self.sel_cls)
        row.addWidget(self.sel_dev, 1)
        left.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(self.btn_add)
        row2.addWidget(self.btn_clear)
        left.addLayout(row2)
        self.lst = QListWidget()
        self.lst.setMaximumHeight(120)
        left.addWidget(self.lst)
        cap.addLayout(left)
        self.p_cap = make_plot("signal", xlabel="t in pulse [ms]")
        self.p_cap.addLegend(offset=(6, 6), labelTextSize="8pt")
        cap.addWidget(self.p_cap, 3)
        self.body.addLayout(cap, 3)
        self._cap_curves: dict[str, pg.PlotDataItem] = {}

        # ---- postmortem
        pm_bar = QHBoxLayout()
        self.btn_pm = QPushButton("Load postmortem (trip pulse)")
        self.lbl_pm = QLabel("no postmortem loaded")
        self.lbl_pm.setStyleSheet("color:#8b96a5;")
        pm_bar.addWidget(self.btn_pm)
        pm_bar.addWidget(self.lbl_pm)
        pm_bar.addStretch(1)
        self.body.addLayout(pm_bar)
        self.p_pm = make_plot("BLM [W/m]", xlabel="t in pulse [ms]")
        self.p_pm.addLegend(offset=(6, 6), labelTextSize="8pt")
        self.body.addWidget(self.p_pm, 2)

        self.sel_cls.currentTextChanged.connect(self._fill_devs)
        self.btn_add.clicked.connect(self._add_dev)
        self.btn_clear.clicked.connect(self._clear_devs)
        self.btn_pm.clicked.connect(self._load_pm)
        self.hub.wfToroid.connect(self._on_tor)
        self.hub.wfCapture.connect(self._on_cap)
        self.hub.mpsEvent.connect(self._on_mps)
        self._fill_devs("bpm")
        self._last_draw = 0.0

    def _fill_devs(self, cls):
        self.sel_dev.clear()
        self.sel_dev.addItems([e.name for e in self.lat.instruments(cls)])

    def _selected(self) -> list[str]:
        return [self.lst.item(i).text() for i in range(self.lst.count())]

    def _add_dev(self):
        names = self._selected()
        n = self.sel_dev.currentText()
        if n and n not in names and len(names) < 8:
            self.lst.addItem(n)
            self.hub.select_waveforms(self._selected())

    def _clear_devs(self):
        self.lst.clear()
        self.p_cap.clear()
        self.p_cap.addLegend(offset=(6, 6), labelTextSize="8pt")
        self._cap_curves.clear()
        self.hub.select_waveforms([])

    def _on_tor(self, _pid, data):
        if not self.isVisible():
            return
        now = time.monotonic()
        if now - self._last_draw < 0.15:   # ~6 Hz redraw for 1000-pt traces
            return
        self._last_draw = now
        name = self.sel_tor.currentText()
        if name in data and "t_ms" in data:
            self.c_tor.setData(data["t_ms"], data[name])

    def _on_cap(self, _pid, data):
        if not self.isVisible() or "t_ms" not in data:
            return
        t = data["t_ms"]
        for i, (key, wf) in enumerate(sorted(data.items())):
            if key == "t_ms":
                continue
            if key not in self._cap_curves:
                pen = pg.mkPen(COLORS[len(self._cap_curves) % len(COLORS)],
                               width=1.2)
                self._cap_curves[key] = self.p_cap.plot(pen=pen, name=key)
            self._cap_curves[key].setData(t, wf)

    def _on_mps(self, ev):
        if ev.get("kind") == "trip":
            self._load_pm()

    def _load_pm(self):
        pm = self.hub.get_postmortem()
        if pm is None:
            self.lbl_pm.setText("no postmortem available")
            return
        pid, data = pm
        self.p_pm.clear()
        self.p_pm.addLegend(offset=(6, 6), labelTextSize="8pt")
        t = data.get("t_ms")
        blm = {k[4:]: v for k, v in data.items() if k.startswith("blm:")}
        peaks = sorted(blm.items(), key=lambda kv: -float(np.max(kv[1])))[:5]
        for i, (name, wf) in enumerate(peaks):
            self.p_pm.plot(t, wf, pen=pg.mkPen(COLORS[i], width=1.4),
                           name=name)
        self.lbl_pm.setText(f"postmortem: trip pulse {pid}, showing top-5 BLMs")
