"""BPM orbit viewer: x / y / phase vs s at 20 Hz with reference-orbit diff."""
from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton

from .. import theme
from . import register
from .common import Page, add_section_shading, make_plot


@register("Orbit")
class OrbitPage(Page):
    title = "BPM Orbit"

    def build(self):
        self.s_bpm = np.array([e.s for e in self.lat.instruments("bpm")])
        bar = QHBoxLayout()
        self.btn_ref = QPushButton("Save reference")
        self.chk_diff = QCheckBox("Show difference")
        self.lbl_rms = QLabel("rms: —")
        bar.addWidget(self.btn_ref)
        bar.addWidget(self.chk_diff)
        bar.addStretch(1)
        bar.addWidget(self.lbl_rms)
        self.body.addLayout(bar)

        self.plots, self.curves = [], []
        for name, unit, color in (("x", "mm", theme.ACCENT),
                                  ("y", "mm", "#ffb74d"),
                                  ("phase", "deg", "#ba68c8")):
            p = make_plot(f"{name} [{unit}]")
            add_section_shading(p, self.lat)
            c = p.plot(pen=pg.mkPen(color, width=1.5),
                       symbol="o", symbolSize=4,
                       symbolBrush=color, symbolPen=None)
            self.plots.append(p)
            self.curves.append(c)
            self.body.addWidget(p, 1)
        self.plots[1].setXLink(self.plots[0])
        self.plots[2].setXLink(self.plots[0])

        self._ref = None
        self._last_draw = 0.0
        self._latest = None
        self.btn_ref.clicked.connect(self._save_ref)
        self.hub.orbit.connect(self._on_orbit)

    def _save_ref(self):
        self._ref = self._latest

    def _on_orbit(self, _pid, data):
        self._latest = data
        now = time.monotonic()
        if now - self._last_draw < 0.08:   # draw at <= 12 Hz, keep data at 20
            return
        self._last_draw = now
        x, y, ph = data["x"] * 1e3, data["y"] * 1e3, data["phase"]
        if self.chk_diff.isChecked() and self._ref is not None:
            x = x - self._ref["x"] * 1e3
            y = y - self._ref["y"] * 1e3
            ph = ph - self._ref["phase"]
        n = min(len(self.s_bpm), len(x))
        self.curves[0].setData(self.s_bpm[:n], x[:n])
        self.curves[1].setData(self.s_bpm[:n], y[:n])
        self.curves[2].setData(self.s_bpm[:n], ph[:n])
        self.lbl_rms.setText(
            f"rms: x {np.std(x):.3f} mm   y {np.std(y):.3f} mm   "
            f"phase {np.std(ph):.2f} deg")
