"""Shared page scaffolding and pyqtgraph helpers."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import theme

pg.setConfigOptions(antialias=True, background=theme.PANEL,
                    foreground=theme.FG)


class Page(QWidget):
    """Base page: title + content layout; subclasses fill self.body."""

    title = "Page"

    def __init__(self, hub, lat):
        super().__init__()
        self.hub = hub
        self.lat = lat
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 8)
        t = QLabel(self.title)
        t.setObjectName("pageTitle")
        outer.addWidget(t)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)
        self.build()

    def build(self):
        raise NotImplementedError


def make_plot(ylabel: str = "", xlabel: str = "s [m]", height: int = 0
              ) -> pg.PlotWidget:
    w = pg.PlotWidget()
    w.showGrid(x=True, y=True, alpha=0.2)
    if ylabel:
        w.setLabel("left", ylabel)
    if xlabel:
        w.setLabel("bottom", xlabel)
    if height:
        w.setFixedHeight(height)
    return w


def section_spans(lat):
    """[(name, s_start, s_end, color), ...] for background section shading."""
    return [(s.name, s.s_start, s.s_end,
             theme.SECTION_COLORS.get(s.name, "#444"))
            for s in lat.sections]


def add_section_shading(plot: pg.PlotWidget, lat, alpha: int = 28):
    for name, s0, s1, color in section_spans(lat):
        c = pg.mkColor(color)
        c.setAlpha(alpha)
        reg = pg.LinearRegionItem((s0, s1), movable=False, brush=c,
                                  pen=pg.mkPen(None))
        reg.setZValue(-10)
        plot.addItem(reg)


def gauss_fit(x: np.ndarray, y: np.ndarray):
    """Moment-based Gaussian estimate; returns (amp, mu, sigma, fit_y)."""
    y = np.maximum(np.asarray(y, dtype=float), 0.0)
    tot = y.sum()
    if tot <= 0:
        return 0.0, 0.0, 1.0, np.zeros_like(x)
    mu = float((x * y).sum() / tot)
    var = float(((x - mu) ** 2 * y).sum() / tot)
    sig = max(np.sqrt(var), 1e-9)
    amp = float(y.max())
    return amp, mu, sig, amp * np.exp(-0.5 * ((x - mu) / sig) ** 2)
