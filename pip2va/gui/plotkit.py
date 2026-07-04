"""Control-room plot toolkit.

CrosshairPlot wraps pyqtgraph with the behaviours operators expect:

* crosshair cursor with a live x/y readout,
* visible grid,
* RIGID auto-Y: expands immediately when data exceeds the range, but only
  shrinks after the data has occupied a small fraction of the range for many
  consecutive updates — no more bouncing axes,
* one-click Y-mode: AUTO (rigid) / LOCK; any manual zoom/pan (wheel, drag,
  right-click menu) switches to LOCK so the plot never fights the user,
* optional categorical "device axis": ticks labelled MEBT:BPM01 instead of
  metres, with a per-plot toggle back to s [m].
"""
from __future__ import annotations

import re

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from . import theme

SHRINK_PATIENCE = 50     # updates the data must stay small before shrinking
SHRINK_FRACTION = 0.45   # ...below this fraction of the current span
PAD = 0.12               # padding around the data span


def short_label(name: str) -> str:
    """MEBT:BPM1 -> MEBT:BPM01 (zero-padded device numbering)."""
    m = re.match(r"^(.*?)(\d+)$", name)
    if not m:
        return name
    return f"{m.group(1)}{int(m.group(2)):02d}"


class DeviceAxis(pg.AxisItem):
    """Bottom axis showing device names at integer positions."""

    def __init__(self, names: list[str]):
        super().__init__(orientation="bottom")
        self.names = [short_label(n) for n in names]
        self.setStyle(tickTextOffset=6)

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            i = int(round(v))
            if abs(v - i) < 0.25 and 0 <= i < len(self.names):
                out.append(self.names[i])
            else:
                out.append("")
        return out


class CrosshairPlot(QWidget):
    """PlotWidget + crosshair readout + rigid auto-Y + axis mode controls."""

    def __init__(self, ylabel: str = "", xlabel: str = "s [m]",
                 device_names: list[str] | None = None, log_y: bool = False):
        super().__init__()
        self.device_names = device_names
        self._use_devices = device_names is not None
        self._log_y = log_y

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(4, 2, 4, 0)
        self.readout = QLabel("")
        self.readout.setStyleSheet("color:#8b96a5; font-size:11px;")
        head.addWidget(self.readout)
        head.addStretch(1)
        self.btn_y = QPushButton("Y: AUTO")
        self.btn_y.setFixedWidth(76)
        self.btn_y.setStyleSheet("font-size:10px; padding:2px;")
        self.btn_y.clicked.connect(self._toggle_y)
        head.addWidget(self.btn_y)
        if device_names is not None:
            self.btn_x = QPushButton("X: device")
            self.btn_x.setFixedWidth(84)
            self.btn_x.setStyleSheet("font-size:10px; padding:2px;")
            self.btn_x.clicked.connect(self._toggle_x)
            head.addWidget(self.btn_x)
        lay.addLayout(head)

        axis_items = {}
        if self._use_devices:
            axis_items["bottom"] = DeviceAxis(device_names)
        self.pw = pg.PlotWidget(axisItems=axis_items)
        self.pw.showGrid(x=True, y=True, alpha=0.35)
        if ylabel:
            self.pw.setLabel("left", ylabel)
        self._xlabel_m = xlabel
        if not self._use_devices and xlabel:
            self.pw.setLabel("bottom", xlabel)
        if log_y:
            self.pw.setLogMode(y=True)
        lay.addWidget(self.pw, 1)

        # crosshair
        pen = pg.mkPen("#7f8b9b", width=1, style=Qt.PenStyle.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        for ln in (self._vline, self._hline):
            ln.setZValue(50)
            ln.hide()
            self.pw.addItem(ln, ignoreBounds=True)
        self.pw.scene().sigMouseMoved.connect(self._mouse_moved)

        # rigid auto-Y state
        self._auto = True
        self._yspan: tuple[float, float] | None = None
        self._small_count = 0
        self.pw.plotItem.vb.sigRangeChangedManually.connect(self._manual_zoom)
        self.pw.plotItem.vb.disableAutoRange()

    # -------------------------------------------------------------- plotting

    def plot(self, *args, **kwargs):
        return self.pw.plot(*args, **kwargs)

    def addItem(self, *args, **kwargs):
        return self.pw.addItem(*args, **kwargs)

    def clear(self):
        self.pw.clear()
        for ln in (self._vline, self._hline):
            self.pw.addItem(ln, ignoreBounds=True)

    def addLegend(self, **kw):
        return self.pw.addLegend(**kw)

    def setXLink(self, other: "CrosshairPlot"):
        self.pw.setXLink(other.pw)

    # ------------------------------------------------------------ rigid auto

    def update_y(self, *arrays):
        """Feed the freshest data so the rigid autoscaler can react."""
        if not self._auto:
            return
        data = np.concatenate([np.asarray(a, dtype=float).ravel()
                               for a in arrays if a is not None and len(a)])
        data = data[np.isfinite(data)]
        if data.size == 0:
            return
        if self._log_y:
            data = np.log10(np.maximum(data, 1e-6))
        lo, hi = float(data.min()), float(data.max())
        span = max(hi - lo, 1e-12)
        pad = span * PAD
        want = (lo - pad, hi + pad)
        if self._yspan is None:
            self._yspan = want
        else:
            cur_lo, cur_hi = self._yspan
            if lo < cur_lo or hi > cur_hi:
                # expand immediately, generously
                self._yspan = (min(lo - pad, cur_lo), max(hi + pad, cur_hi))
                self._small_count = 0
            elif span < SHRINK_FRACTION * (cur_hi - cur_lo):
                self._small_count += 1
                if self._small_count >= SHRINK_PATIENCE:
                    self._yspan = want
                    self._small_count = 0
            else:
                self._small_count = 0
        self.pw.setYRange(*self._yspan, padding=0)

    def _toggle_y(self):
        self._set_auto(not self._auto)

    def _set_auto(self, auto: bool):
        self._auto = auto
        self._yspan = None
        self._small_count = 0
        self.btn_y.setText("Y: AUTO" if auto else "Y: LOCK")
        self.btn_y.setStyleSheet(
            "font-size:10px; padding:2px;" +
            ("" if auto else f"color:{theme.WARN};"))

    def _manual_zoom(self, *_):
        if self._auto:
            self._set_auto(False)   # user took the wheel: stop auto-scaling

    # ------------------------------------------------------------ crosshair

    def _mouse_moved(self, pos):
        vb = self.pw.plotItem.vb
        if not self.pw.sceneBoundingRect().contains(pos):
            self._vline.hide()
            self._hline.hide()
            self.readout.setText("")
            return
        p = vb.mapSceneToView(pos)
        self._vline.setPos(p.x())
        self._hline.setPos(p.y())
        self._vline.show()
        self._hline.show()
        y = 10 ** p.y() if self._log_y else p.y()
        if self._use_devices and self.device_names:
            i = int(round(p.x()))
            if 0 <= i < len(self.device_names):
                self.readout.setText(
                    f"{short_label(self.device_names[i])}   y={y:.4g}")
                return
        self.readout.setText(f"x={p.x():.3f}   y={y:.4g}")

    # ------------------------------------------------------------ axis mode

    def _toggle_x(self):
        self._use_devices = not self._use_devices
        self.btn_x.setText("X: device" if self._use_devices else "X: s [m]")
        if self._use_devices:
            self.pw.setAxisItems({"bottom": DeviceAxis(self.device_names)})
            self.pw.setLabel("bottom", "")
        else:
            self.pw.setAxisItems({"bottom": pg.AxisItem(orientation="bottom")})
            self.pw.setLabel("bottom", self._xlabel_m)
        self.pw.plotItem.vb.enableAutoRange(x=True)
        if self._xmode_cb:
            self._xmode_cb(self._use_devices)

    _xmode_cb = None

    def on_xmode(self, cb):
        """cb(use_devices: bool) — caller swaps x-data and axis labels."""
        self._xmode_cb = cb
