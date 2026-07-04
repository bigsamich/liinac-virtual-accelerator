"""Beam-loss display: per-BLM bars (device axis) plus a scrolling waterfall."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSpinBox

from .. import theme
from ..plotkit import CrosshairPlot, short_label
from . import register
from .common import Page


@register("Losses")
class LossesPage(Page):
    title = "Beam Loss Monitors"

    def build(self):
        blms = self.lat.instruments("blm")
        self.blm_names = [e.name for e in blms]
        self.s_blm = np.array([e.s for e in blms])
        nblm = len(blms)
        self.x_idx = np.arange(nblm, dtype=float)
        self._use_dev = True

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Integration window [pulses]:"))
        self.spin_avg = QSpinBox()
        self.spin_avg.setRange(1, 100)
        self.spin_avg.setValue(10)
        bar.addWidget(self.spin_avg)
        bar.addStretch(1)
        self.lbl_worst = QLabel("worst: —")
        bar.addWidget(self.lbl_worst)
        self.body.addLayout(bar)

        self.p_bar = CrosshairPlot("loss [W/m]", device_names=self.blm_names,
                                   log_y=True)
        self.p_bar.on_xmode(self._xmode_changed)
        self.bars = pg.BarGraphItem(x=self.x_idx, height=np.zeros(nblm),
                                    width=0.7, brush=theme.ACCENT)
        self.p_bar.addItem(self.bars)
        for level, color in ((0.1, theme.WARN), (1.0, theme.ALARM)):
            self.p_bar.addItem(pg.InfiniteLine(
                pos=np.log10(level), angle=0,
                pen=pg.mkPen(color, style=pg.QtCore.Qt.PenStyle.DashLine)))
        self.p_bar.pw.setYRange(-3.2, 1.0)
        self.body.addWidget(self.p_bar, 2)

        # waterfall: rows = pulses, cols = BLMs (device index)
        self.p_wf = CrosshairPlot("history [s]", xlabel="BLM index")
        self.img = pg.ImageItem(axisOrder="row-major")
        self.img.setLookupTable(pg.colormap.get("inferno").getLookupTable())
        self.p_wf.addItem(self.img)
        self.img.setRect(pg.QtCore.QRectF(-0.5, 0.0, float(nblm), 6.0))
        self.p_wf.pw.setYRange(0, 6)
        self.p_wf.pw.setXRange(-0.5, nblm - 0.5)
        self.body.addWidget(self.p_wf, 2)

        self.hist = collections.deque(maxlen=120)
        self.window = collections.deque(maxlen=10)
        self.hub.losses.connect(self._on_losses)
        self.spin_avg.valueChanged.connect(
            lambda n: setattr(self, "window",
                              collections.deque(self.window, maxlen=n)))

    def _xmode_changed(self, use_dev: bool):
        self._use_dev = use_dev
        self.bars.setOpts(x=self.x_idx if use_dev else self.s_blm,
                          width=0.7 if use_dev else 1.2)

    def _on_losses(self, _pid, data):
        if not self.isVisible():
            return
        wpm = data["wpm"]
        self.window.append(wpm)
        self.hist.append(wpm)
        mean = np.mean(np.stack(self.window), axis=0)
        self.bars.setOpts(height=np.maximum(mean, 1e-4))
        j = int(np.argmax(mean))
        nm = short_label(self.blm_names[j]) if j < len(self.blm_names) \
            else f"BLM{j}"
        self.lbl_worst.setText(f"worst: {nm}  {mean[j]:.3f} W/m")
        if len(self.hist) > 2:
            img = np.log10(np.maximum(np.stack(self.hist), 1e-4))
            self.img.setImage(img, autoLevels=False, levels=(-4, 1))
