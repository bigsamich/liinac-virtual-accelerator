"""Beam-loss display: a tall vertical per-BLM histogram on the left and a
scrolling waterfall on the right. Both share one BLM-index axis (vertical),
labelled with the machine section identifiers so the two line up."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSpinBox

from .. import theme
from ..plotkit import short_label
from . import register
from .common import Page

_PULSE_HZ = 20.0                      # waterfall time scale (pulse rate)


class _PowAxis(pg.AxisItem):
    """Axis that labels log10 values back as their linear loss [W/m]."""

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            p = 10.0 ** v
            if p >= 1:
                out.append(f"{p:.0f}")
            elif p >= 0.01:
                out.append(f"{p:.2g}")
            else:
                out.append(f"1e{int(round(v))}")
        return out


class _SectionAxis(pg.AxisItem):
    """Left axis: labels BLM-index positions with their section name."""

    def __init__(self, ticks):
        super().__init__(orientation="left")
        self._sticks = ticks          # [(blm_index, section_name), ...]
        self.setStyle(tickTextOffset=4)
        self.setWidth(52)
        self.setTextPen(theme.FG)

    def tickValues(self, minVal, maxVal, size):
        lo, hi = min(minVal, maxVal), max(minVal, maxVal)
        vals = [float(i) for i, _ in self._sticks if lo - 1 <= i <= hi + 1]
        return [(1.0, vals)]

    def tickStrings(self, values, scale, spacing):
        d = {int(i): n for i, n in self._sticks}
        return [d.get(int(round(v)), "") for v in values]


@register("Losses")
class LossesPage(Page):
    title = "Beam Loss Monitors"

    def build(self):
        blms = self.lat.instruments("blm")
        self.blm_names = [e.name for e in blms]
        nblm = len(blms)
        self.x_idx = np.arange(nblm, dtype=float)

        # one tick per section at its first BLM, for both plots' y-axis
        sticks, seen = [], set()
        for i, e in enumerate(blms):
            if e.section not in seen:
                seen.add(e.section)
                sticks.append((i, e.section))

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

        row = QHBoxLayout()
        row.setSpacing(4)

        # ---- LEFT: tall skinny vertical histogram (loss on x, BLM idx on y)
        self.p_bar = pg.PlotWidget(axisItems={
            "left": _SectionAxis(sticks),
            "bottom": _PowAxis(orientation="bottom")})
        self.p_bar.setLabel("bottom", "loss [W/m]")
        self.p_bar.showGrid(x=True, y=True, alpha=0.2)
        self.p_bar.setXRange(-4, 2.3, padding=0)
        self.p_bar.setYRange(-0.5, nblm - 0.5, padding=0)
        self.p_bar.getViewBox().invertY(True)      # BLM 0 (LEBT) at the top
        self.p_bar.getViewBox().setMouseEnabled(x=False, y=True)
        self.bars = pg.BarGraphItem(x0=-4.0, y=self.x_idx, height=0.85,
                                    width=np.full(nblm, 1e-6),
                                    brush=theme.ACCENT, pen=None)
        self.p_bar.addItem(self.bars)
        for level, color in ((0.1, theme.WARN), (1.0, theme.ALARM)):
            self.p_bar.addItem(pg.InfiniteLine(
                pos=np.log10(level), angle=90,
                pen=pg.mkPen(color, style=pg.QtCore.Qt.PenStyle.DashLine)))
        self.p_bar.setMaximumWidth(320)
        row.addWidget(self.p_bar)

        # ---- RIGHT: waterfall (time on x, BLM idx on y) — vertical viewing
        self.p_wf = pg.PlotWidget(axisItems={"left": _SectionAxis(sticks)})
        self.p_wf.setLabel("bottom", "history [s]")
        self.p_wf.showGrid(x=True, y=True, alpha=0.12)
        self.img = pg.ImageItem(axisOrder="row-major")
        self.img.setLookupTable(pg.colormap.get("inferno").getLookupTable())
        self.p_wf.addItem(self.img)
        self.p_wf.setYRange(-0.5, nblm - 0.5, padding=0)
        self.p_wf.setXRange(-6.0, 0.0, padding=0)  # fixed 6 s window (not zoomed in)
        self.p_wf.getViewBox().invertY(True)
        self.p_wf.getViewBox().setMouseEnabled(x=True, y=True)
        self.p_wf.setYLink(self.p_bar)             # sections stay aligned
        row.addWidget(self.p_wf, 1)

        self.body.addLayout(row, 1)

        self.hist = collections.deque(maxlen=200)
        self.window = collections.deque(maxlen=10)
        self.hub.losses.connect(self._on_losses)
        self.spin_avg.valueChanged.connect(
            lambda n: setattr(self, "window",
                              collections.deque(self.window, maxlen=n)))
        self._thr_gate = 0

    def _on_losses(self, _pid, data):
        if not self.isVisible():
            return
        wpm = data["wpm"]
        self.window.append(wpm)
        self.hist.append(wpm)
        mean = np.mean(np.stack(self.window), axis=0)
        logv = np.log10(np.maximum(mean, 1e-4))
        self.bars.setOpts(width=logv + 4.0)        # bars from -4 to log10(loss)
        j = int(np.argmax(mean))
        nm = short_label(self.blm_names[j]) if j < len(self.blm_names) \
            else f"BLM{j}"
        self.lbl_worst.setText(f"worst: {nm}  {mean[j]:.3f} W/m")
        if len(self.hist) > 2:
            # rows = BLM index (y), cols = time (x)
            img = np.log10(np.maximum(np.stack(self.hist), 1e-4)).T
            self.img.setImage(img, autoLevels=False, levels=(-4, 1))
            npulse = img.shape[1]
            span = npulse / _PULSE_HZ               # seconds of history shown
            self.img.setRect(pg.QtCore.QRectF(-span, -0.5, span, float(len(
                self.blm_names))))
