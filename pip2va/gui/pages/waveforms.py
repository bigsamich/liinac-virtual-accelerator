"""Intra-pulse waveform viewer.

Check devices in the tree — they start streaming immediately. Currents
(toroids, BPM sum) and signals (BPM position, BLM loss) get separate plots so
units never mix. The Postmortem tab shows the frozen trip pulse.
"""
from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTabWidget,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

from .. import theme
from ..plotkit import CrosshairPlot, short_label
from . import register
from .common import Page

COLORS = [theme.ACCENT, "#ffb74d", "#ba68c8", "#4db6ac", "#e57373",
          "#aed581", "#f06292", "#90a4ae"]
MAX_SEL = 8


@register("Waveforms")
class WaveformsPage(Page):
    title = "Intra-Pulse Waveforms (1000 samples / 0.55 ms)"

    def build(self):
        lay = QHBoxLayout()

        # ---- device tree (checkable, instant apply)
        left = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Devices (check up to 8)")
        self.tree.setFixedWidth(230)
        self._items: dict[str, QTreeWidgetItem] = {}
        groups = [("Toroids", "toroid", self.lat.instruments("toroid")),
                  ("Cavities (RF)", "rf",
                   [e for e in self.lat.elements
                    if e.type in ("rfgap", "rfq")]),
                  ("BPMs", "bpm", self.lat.instruments("bpm")),
                  ("BLMs", "blm", self.lat.instruments("blm"))]
        for group, typ, els in groups:
            g = QTreeWidgetItem([group])
            g.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(g)
            for e in els:
                it = QTreeWidgetItem([short_label(e.name)])
                it.setData(0, Qt.ItemDataRole.UserRole, (typ, e.name))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Unchecked)
                g.addChild(it)
                self._items[e.name] = it
        for g in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(g).setExpanded(g == 0)
        # sensible default: last toroid checked
        last_tor = self.lat.instruments("toroid")[-1].name
        self._items[last_tor].setCheckState(0, Qt.CheckState.Checked)
        left.addWidget(self.tree, 1)
        btn_none = QPushButton("Uncheck all")
        left.addWidget(btn_none)
        lay.addLayout(left)

        # ---- plots
        tabs = QTabWidget()
        live = QWidget()
        vlay = QVBoxLayout(live)
        self.p_cur = CrosshairPlot("current [mA]", xlabel="t in pulse [ms]")
        self.p_cur.addLegend(offset=(6, 6), labelTextSize="8pt")
        self.p_sig = CrosshairPlot("position [mm] / loss [W/m]",
                                   xlabel="t in pulse [ms]")
        self.p_sig.addLegend(offset=(6, 6), labelTextSize="8pt")
        vlay.addWidget(self.p_cur, 1)
        vlay.addWidget(self.p_sig, 1)
        tabs.addTab(live, "Live")

        pm = QWidget()
        pmlay = QVBoxLayout(pm)
        bar = QHBoxLayout()
        self.btn_pm = QPushButton("Reload postmortem")
        self.lbl_pm = QLabel("loads automatically on a trip")
        self.lbl_pm.setStyleSheet("color:#8b96a5;")
        bar.addWidget(self.btn_pm)
        bar.addWidget(self.lbl_pm)
        bar.addStretch(1)
        pmlay.addLayout(bar)
        self.p_pm = CrosshairPlot("BLM [W/m]", xlabel="t in pulse [ms]")
        self.p_pm.addLegend(offset=(6, 6), labelTextSize="8pt")
        pmlay.addWidget(self.p_pm, 1)
        tabs.addTab(pm, "Postmortem (trip pulse)")
        lay.addWidget(tabs, 1)
        self.body.addLayout(lay, 1)
        self.tabs = tabs

        self._cur_curves: dict[str, pg.PlotDataItem] = {}
        self._sig_curves: dict[str, pg.PlotDataItem] = {}
        self._checked: dict[str, str] = {last_tor: "toroid"}
        self._last_draw = 0.0
        self._color_i = 0

        self.tree.itemChanged.connect(self._on_check)
        btn_none.clicked.connect(self._uncheck_all)
        self.btn_pm.clicked.connect(self._load_pm)
        self.hub.wfToroid.connect(self._on_tor)
        self.hub.wfCapture.connect(self._on_cap)
        self.hub.wfRf.connect(self._on_rf_wf)
        self.hub.mpsEvent.connect(self._on_mps)

    # ------------------------------------------------------------ selection

    def _on_check(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return
        typ, name = data
        if item.checkState(0) == Qt.CheckState.Checked:
            if len(self._checked) >= MAX_SEL:
                self.tree.blockSignals(True)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                self.tree.blockSignals(False)
                return
            self._checked[name] = typ
        else:
            self._checked.pop(name, None)
            self._drop_curves(name)
        # BPM/BLM captures come from diag-sim; RF waveforms from rf-sim
        self.hub.select_waveforms(
            [n for n, t in self._checked.items() if t in ("bpm", "blm")],
            [n for n, t in self._checked.items() if t == "rf"])

    def _uncheck_all(self):
        self.tree.blockSignals(True)
        for it in self._items.values():
            it.setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._checked.clear()
        self.hub.select_waveforms([])
        for name in list(self._cur_curves) + list(self._sig_curves):
            self._drop_curves(name.split("|")[0])
        self._cur_curves.clear()
        self._sig_curves.clear()
        self.p_cur.clear()
        self.p_cur.addLegend(offset=(6, 6), labelTextSize="8pt")
        self.p_sig.clear()
        self.p_sig.addLegend(offset=(6, 6), labelTextSize="8pt")

    def _drop_curves(self, name: str):
        for store, plot in ((self._cur_curves, self.p_cur),
                            (self._sig_curves, self.p_sig)):
            for key in [k for k in store if k.startswith(name)]:
                plot.pw.removeItem(store.pop(key))

    def _curve(self, store, plot, key: str):
        if key not in store:
            pen = pg.mkPen(COLORS[self._color_i % len(COLORS)], width=1.3)
            self._color_i += 1
            store[key] = plot.plot(pen=pen, name=short_label(key))
        return store[key]

    # ------------------------------------------------------------ live data

    def _throttled(self) -> bool:
        now = time.monotonic()
        if now - self._last_draw < 0.15:
            return True
        self._last_draw = now
        return False

    def _on_tor(self, _pid, data):
        if not self.isVisible() or "t_ms" not in data or self._throttled():
            return
        t = data["t_ms"]
        vals = []
        for name, typ in self._checked.items():
            if typ == "toroid" and name in data:
                self._curve(self._cur_curves, self.p_cur,
                            f"{name}|i").setData(t, data[name])
                vals.append(data[name])
        if vals:
            self.p_cur.update_y(*vals)

    def _on_cap(self, _pid, data):
        if not self.isVisible() or "t_ms" not in data:
            return
        t = data["t_ms"]
        sig_vals, cur_vals = [], []
        for key, wf in data.items():
            if key == "t_ms":
                continue
            name, field = key.rsplit(":", 1)
            if name not in self._checked:
                continue
            if field in ("x", "y"):
                c = self._curve(self._sig_curves, self.p_sig,
                                f"{name}|{field}")
                c.setData(t, wf * 1e3)     # m -> mm
                sig_vals.append(wf * 1e3)
            elif field == "wpm":
                c = self._curve(self._sig_curves, self.p_sig, f"{name}|wpm")
                c.setData(t, wf)
                sig_vals.append(wf)
            elif field in ("sum", "i"):
                c = self._curve(self._cur_curves, self.p_cur,
                                f"{name}|{field}")
                c.setData(t, wf)
                cur_vals.append(wf)
        if sig_vals:
            self.p_sig.update_y(*sig_vals)
        if cur_vals:
            self.p_cur.update_y(*cur_vals)

    def _on_rf_wf(self, _pid, data):
        if not self.isVisible() or "t_ms" not in data:
            return
        t = data["t_ms"]
        sig_vals = []
        for key, wf in data.items():
            if key == "t_ms":
                continue
            name, field = key.rsplit(":", 1)
            if name not in self._checked:
                continue
            if field in ("amp", "det"):
                c = self._curve(self._sig_curves, self.p_sig,
                                f"{name}|{field}")
                c.setData(t, wf)
                sig_vals.append(wf)
            elif field == "fwd_kw":
                c = self._curve(self._cur_curves, self.p_cur,
                                f"{name}|fwd")
                c.setData(t, wf)
        if sig_vals:
            self.p_sig.update_y(*sig_vals)

    # ------------------------------------------------------------ postmortem

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
                           name=short_label(name))
        if peaks:
            self.p_pm.update_y(*[wf for _, wf in peaks])
        self.lbl_pm.setText(f"trip pulse {pid} — top-5 BLMs shown")
