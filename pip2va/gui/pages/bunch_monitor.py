"""RWCM bunch monitor: scope-style view of the actual bunch train.

Reconstructs what the 4 GHz-bandwidth resistive wall current monitor sees:
~1 sigma_t Gaussian bunches on the 162.5 MHz bucket grid (6.153 ns), the
chopper pattern carving bunches out at 1e-4 extinction, and the 162.5 MHz
RF reference overlaid. Bar mode shows per-bucket charge instead.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel

from .. import theme
from ..plotkit import CrosshairPlot
from . import register
from .common import Page

T_BUCKET_NS = 1e3 / 162.5      # 6.1538 ns


@register("Bunch Monitor")
class BunchMonitorPage(Page):
    title = "RWCM — bunch-by-bunch wall current monitor"

    def build(self):
        bar = QHBoxLayout()
        bar.addWidget(QLabel("monitor:"))
        self.sel = QComboBox()
        self.sel.addItems(["MEBT:WCM1", "BTL:WCM1"])
        bar.addWidget(self.sel)
        self.chk_scope = QCheckBox("scope trace (bunch structure)")
        self.chk_scope.setChecked(True)
        bar.addWidget(self.chk_scope)
        self.chk_log = QCheckBox("log (see 1e-4 extinction)")
        bar.addWidget(self.chk_log)
        self.chk_rf = QCheckBox("162.5 MHz RF reference")
        self.chk_rf.setChecked(True)
        bar.addWidget(self.chk_rf)
        self.lbl = QLabel("")
        bar.addWidget(self.lbl, 1)
        self.body.addLayout(bar)

        self.p = CrosshairPlot("I [mA]", xlabel="time [ns]")
        self.c_tr = self.p.plot(pen=pg.mkPen("#ffd54f", width=1.2),
                                name="RWCM")
        self.c_rf = self.p.plot(pen=pg.mkPen("#4b6a8a", width=0.9),
                                name="RF ref")
        self.p.addLegend(offset=(6, 6), labelTextSize="8pt")
        self.body.addWidget(self.p, 3)

        self.p_bar = CrosshairPlot("bunch charge [nC]", xlabel="bucket")
        self.bars = pg.BarGraphItem(x=np.arange(160),
                                    height=np.zeros(160), width=0.8,
                                    brush="#ffd54f")
        self.p_bar.addItem(self.bars)
        self.body.addWidget(self.p_bar, 2)

        self._gate = 0
        self.hub.wcm.connect(self._on_wcm)

    def _on_wcm(self, _pid, data):
        self._gate += 1
        if not self.isVisible() or self._gate % 4:
            return
        name = self.sel.currentText()
        q = data.get(f"{name}:q_nc")
        if q is None:
            return
        q = np.asarray(q, dtype=float)
        sig = data.get(f"{name}:sig_ps")
        sig_ns = float(sig[0]) * 1e-3 if sig is not None and len(sig) \
            else 0.3
        self.lbl.setText(f"bunch length {sig_ns * 1e3:.0f} ps rms — "
                         f"{np.sum(q > q.max() * 0.5)} of {len(q)} "
                         f"buckets filled")

        # bar view: per-bucket charge
        if self.chk_log.isChecked():
            self.bars.setOpts(height=np.log10(np.maximum(q, 1e-7)) + 7)
            self.p_bar.pw.setLabel("left", "log10(q/nC)+7")
        else:
            self.bars.setOpts(height=q)
            self.p_bar.pw.setLabel("left", "bunch charge [nC]")
        self.p_bar.update_y(q)

        # scope view: 32 buckets of real structure at RWCM bandwidth
        if not self.chk_scope.isChecked():
            self.c_tr.setData([], [])
            self.c_rf.setData([], [])
            return
        nb = 32
        t = np.linspace(0, nb * T_BUCKET_NS, 2400)
        sig_eff = max(sig_ns, 0.12)     # 4 GHz bandwidth floor ~0.1 ns
        tr = np.zeros_like(t)
        for k in range(nb):
            tc = (k + 0.5) * T_BUCKET_NS
            # peak current of a Gaussian bunch: q / (sqrt(2pi) sigma)
            tr += (q[k] / (np.sqrt(2 * np.pi) * sig_eff)
                   * np.exp(-0.5 * ((t - tc) / sig_eff) ** 2))
        tr_ma = tr * 1e3                # nC/ns -> A -> mA is x1e3... (uA->mA)
        if self.chk_log.isChecked():
            tr_ma = np.log10(np.maximum(tr_ma, 1e-6)) + 6
            self.p.pw.setLabel("left", "log10(I/mA)+6")
        else:
            self.p.pw.setLabel("left", "I [mA]")
        self.c_tr.setData(t, tr_ma)
        if self.chk_rf.isChecked() and not self.chk_log.isChecked():
            self.c_rf.setData(t, tr_ma.max() * 0.15
                              * np.cos(2 * np.pi * t / T_BUCKET_NS) if
                              tr_ma.max() > 0 else np.zeros_like(t))
        else:
            self.c_rf.setData([], [])
        self.p.update_y(tr_ma)
