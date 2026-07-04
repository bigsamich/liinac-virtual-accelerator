"""Instrumentation dashboard: toroids, transmission, device health."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel

from .. import theme
from ..widgets import BigValue
from . import register
from .common import Page, make_plot


@register("Instrumentation")
class InstrumentationPage(Page):
    title = "Instrumentation Dashboard"

    def build(self):
        self.tors = self.lat.instruments("toroid")

        row = QHBoxLayout()
        self.v_first = BigValue(f"{self.tors[0].name}", "mA", "{:.3f}")
        self.v_last = BigValue(f"{self.tors[-1].name}", "mA", "{:.3f}")
        self.v_ratio = BigValue("End-to-end transmission", "%", "{:.2f}")
        self.v_charge = BigValue("Pulse charge", "µC", "{:.3f}")
        for v in (self.v_first, self.v_last, self.v_ratio, self.v_charge):
            row.addWidget(v)
        self.body.addLayout(row)

        # toroid strip chart
        self.p_tor = make_plot("I [mA]", xlabel="pulse")
        self.curves = []
        cmap = pg.colormap.get("CET-C6s")
        for k, t in enumerate(self.tors):
            pen = pg.mkPen(cmap.map(k / max(len(self.tors) - 1, 1),
                                    mode="qcolor"), width=1.5)
            self.curves.append(self.p_tor.plot(pen=pen, name=t.name))
        self.p_tor.addLegend(offset=(6, 6), labelTextSize="8pt")
        self.body.addWidget(self.p_tor, 2)

        # per-section transmission bars from adjacent toroid ratios
        self.p_bars = make_plot("section T [%]", xlabel="")
        self.bars = pg.BarGraphItem(x=np.arange(len(self.tors) - 1),
                                    height=np.zeros(len(self.tors) - 1),
                                    width=0.6, brush=theme.ACCENT)
        self.p_bars.addItem(self.bars)
        ax = self.p_bars.getAxis("bottom")
        ax.setTicks([[(k, f"{self.tors[k].section}→{self.tors[k+1].section}")
                      for k in range(len(self.tors) - 1)]])
        self.body.addWidget(self.p_bars, 1)

        # device health summary
        self.lbl_health = QLabel("device health: —")
        self.body.addWidget(self.lbl_health)

        self.hist = [collections.deque(maxlen=400) for _ in self.tors]
        self.hub.toroids.connect(self._on_toroids)
        self.hub.rf.connect(self._on_rf)
        self.hub.magnets.connect(self._on_magnets)
        self._rf_trips = 0
        self._mag_trips = 0
        self.pulse_ms = self.lat.meta.get("beam_ms", 0.54)

    def _on_toroids(self, _pid, data):
        i = data["i_ma"]
        n = min(len(i), len(self.hist))
        for k in range(n):
            self.hist[k].append(float(i[k]))
            self.curves[k].setData(np.arange(len(self.hist[k])),
                                   np.fromiter(self.hist[k], float))
        if n >= 2:
            self.v_first.set(float(i[0]))
            self.v_last.set(float(i[-1]))
            # transmission vs the post-chop reference (toroid 2 onward)
            ref = max(float(i[2]) if n > 2 else float(i[0]), 1e-6)
            t = 100.0 * float(i[-1]) / ref
            self.v_ratio.set(min(t, 110.0),
                             theme.OK if t > 95 else theme.ALARM)
            self.v_charge.set(float(i[-1]) * 1e-3 * self.pulse_ms * 1e3)
            r = np.maximum(i[:-1], 1e-6)
            self.bars.setOpts(height=np.clip(100.0 * i[1:] / r, 0, 110))

    def _on_rf(self, _pid, data):
        self._rf_trips = int(np.sum(data["status"] > 0.5))
        self._update_health()

    def _on_magnets(self, _pid, data):
        self._mag_trips = int(np.sum(data["status"] > 0.5))
        self._update_health()

    def _update_health(self):
        ok = self._rf_trips == 0 and self._mag_trips == 0
        self.lbl_health.setText(
            f"device health: {'ALL OK' if ok else 'FAULTS PRESENT'} — "
            f"RF trips: {self._rf_trips}, magnet trips: {self._mag_trips}")
        self.lbl_health.setStyleSheet(
            f"color: {theme.OK if ok else theme.ALARM}; font-weight: bold;")
