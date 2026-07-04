"""Beam-loss display: BLM bars vs s plus a scrolling waterfall."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSpinBox

from .. import theme
from . import register
from .common import Page, add_section_shading, make_plot


@register("Losses")
class LossesPage(Page):
    title = "Beam Loss Monitors"

    def build(self):
        self.s_blm = np.array([e.s for e in self.lat.instruments("blm")])
        nblm = len(self.s_blm)

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

        self.p_bar = make_plot("loss [W/m]")
        add_section_shading(self.p_bar, self.lat)
        self.bars = pg.BarGraphItem(x=self.s_blm, height=np.zeros(nblm),
                                    width=1.4, brush=theme.ACCENT)
        self.p_bar.addItem(self.bars)
        for level, color in ((0.1, theme.WARN), (1.0, theme.ALARM)):
            line = pg.InfiniteLine(pos=level, angle=0,
                                   pen=pg.mkPen(color, style=pg.QtCore.Qt.PenStyle.DashLine))
            self.p_bar.addItem(line)
        self.p_bar.setLogMode(y=True)
        self.p_bar.setYRange(-3.2, 1.0)
        self.body.addWidget(self.p_bar, 2)

        # waterfall: rows = pulses, cols = BLMs
        self.p_wf = make_plot("history [s]", xlabel="s [m]")
        self.img = pg.ImageItem(axisOrder="row-major")
        self.img.setLookupTable(pg.colormap.get("inferno").getLookupTable())
        self.p_wf.addItem(self.img)
        self.img.setRect(pg.QtCore.QRectF(
            float(self.s_blm[0]), 0.0,
            float(self.s_blm[-1] - self.s_blm[0]), 6.0))
        self.body.addWidget(self.p_wf, 2)

        self.hist = collections.deque(maxlen=120)
        self.window = collections.deque(maxlen=10)
        self.hub.losses.connect(self._on_losses)
        self.spin_avg.valueChanged.connect(
            lambda n: setattr(self, "window", collections.deque(self.window, maxlen=n)))

    def _on_losses(self, _pid, data):
        wpm = data["wpm"]
        self.window.append(wpm)
        self.hist.append(wpm)
        mean = np.mean(np.stack(self.window), axis=0)
        self.bars.setOpts(height=np.maximum(mean, 1e-4))
        j = int(np.argmax(mean))
        names = [e.name for e in self.lat.instruments("blm")]
        nm = names[j] if j < len(names) else f"BLM{j}"
        self.lbl_worst.setText(f"worst: {nm}  {mean[j]:.3f} W/m")
        if len(self.hist) > 2:
            img = np.log10(np.maximum(np.stack(self.hist), 1e-4))
            self.img.setImage(img, autoLevels=False, levels=(-4, 1))
