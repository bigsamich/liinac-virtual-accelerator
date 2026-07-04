"""BPM orbit viewer: x / y / phase per BPM at 20 Hz, reference diff,
and a corrector-usage strip so steering budget is visible at a glance."""
from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton

from .. import theme
from ..plotkit import CrosshairPlot
from . import register
from .common import Page


@register("Orbit")
class OrbitPage(Page):
    title = "BPM Orbit & Steering"

    def build(self):
        bpms = self.lat.instruments("bpm")
        self.bpm_names = [e.name for e in bpms]
        self.s_bpm = np.array([e.s for e in bpms])
        self.x_idx = np.arange(len(bpms), dtype=float)
        self._use_dev = True

        bar = QHBoxLayout()
        self.btn_ref = QPushButton("Save reference")
        self.chk_diff = QCheckBox("Show difference")
        self.lbl_rms = QLabel("rms: —")
        bar.addWidget(self.btn_ref)
        bar.addWidget(self.chk_diff)
        bar.addStretch(1)
        bar.addWidget(self.lbl_rms)
        self.body.addLayout(bar)

        self.plots: list[CrosshairPlot] = []
        self.curves = []
        for name, unit, color in (("x", "mm", theme.ACCENT),
                                  ("y", "mm", "#ffb74d"),
                                  ("phase", "deg", "#ba68c8")):
            p = CrosshairPlot(f"{name} [{unit}]",
                              device_names=self.bpm_names)
            c = p.plot(pen=pg.mkPen(color, width=1.5), symbol="o",
                       symbolSize=4, symbolBrush=color, symbolPen=None)
            p.on_xmode(self._xmode_changed)
            self.plots.append(p)
            self.curves.append(c)
            self.body.addWidget(p, 2)
        self.plots[1].setXLink(self.plots[0])
        self.plots[2].setXLink(self.plots[0])

        # corrector steering budget
        corrs = [e for e in self.lat.elements if e.type == "corrector"]
        self.corr_keys = [f"{e.name}:{f}" for e in corrs
                          for f in ("current_x", "current_y")]
        self.p_corr = CrosshairPlot("trim [A]", device_names=self.corr_keys)
        self.corr_bars = pg.BarGraphItem(
            x=np.arange(len(self.corr_keys)),
            height=np.zeros(len(self.corr_keys)), width=0.7,
            brush=theme.OK)
        self.p_corr.addItem(self.corr_bars)
        lbl = QLabel("Corrector usage (steering budget, ±10 A supplies):")
        lbl.setStyleSheet("color:#8b96a5;")
        self.body.addWidget(lbl)
        self.body.addWidget(self.p_corr, 1)

        self._ref = None
        self._last_draw = 0.0
        self._latest = None
        self._mag_index = None
        self.btn_ref.clicked.connect(self._save_ref)
        self.hub.orbit.connect(self._on_orbit)
        self.hub.magnets.connect(self._on_magnets)

    def _xmode_changed(self, use_dev: bool):
        self._use_dev = use_dev

    def _save_ref(self):
        self._ref = self._latest

    def _xs(self):
        return self.x_idx if self._use_dev else self.s_bpm

    def _on_orbit(self, _pid, data):
        self._latest = data
        now = time.monotonic()
        if not self.isVisible() or now - self._last_draw < 0.08:
            return
        self._last_draw = now
        x, y, ph = data["x"] * 1e3, data["y"] * 1e3, data["phase"]
        if self.chk_diff.isChecked() and self._ref is not None:
            x = x - self._ref["x"] * 1e3
            y = y - self._ref["y"] * 1e3
            ph = ph - self._ref["phase"]
        xs = self._xs()
        n = min(len(xs), len(x))
        for curve, vals in zip(self.curves, (x, y, ph)):
            curve.setData(xs[:n], vals[:n])
        for p, vals in zip(self.plots, (x, y, ph)):
            p.update_y(vals[:n])
        self.lbl_rms.setText(
            f"rms: x {np.std(x):.3f} mm   y {np.std(y):.3f} mm   "
            f"phase {np.std(ph):.2f} deg")

    def _on_magnets(self, _pid, data):
        if not self.isVisible():
            return
        if self._mag_index is None:
            idx = self.hub.get_index("magnet")
            self._mag_index = {k: j for j, k in enumerate(idx)} if idx else None
        if not self._mag_index:
            return
        vals = np.zeros(len(self.corr_keys))
        for i, key in enumerate(self.corr_keys):
            j = self._mag_index.get(key)
            if j is not None and j < len(data["values"]):
                vals[i] = data["values"][j]
        colors = [theme.ALARM if abs(v) > 8 else
                  theme.WARN if abs(v) > 5 else theme.OK for v in vals]
        self.corr_bars.setOpts(height=vals,
                               brushes=[pg.mkBrush(c) for c in colors])
        self.p_corr.update_y(vals, np.array([-1.0, 1.0]))
