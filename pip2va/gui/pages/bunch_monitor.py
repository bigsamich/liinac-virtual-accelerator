"""RWCM bunch monitor: scope-style view of the actual bunch train.

Reconstructs what the 4 GHz-bandwidth resistive wall current monitor sees:
~1 sigma_t Gaussian bunches on the 162.5 MHz bucket grid (6.153 ns), the
chopper pattern carving bunches out at 1e-4 extinction, and the 162.5 MHz
RF reference overlaid. Bar mode shows per-bucket charge instead.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSpinBox)

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

        # ---- bunch pattern generator
        pg_bar = QHBoxLayout()
        pg_bar.addWidget(QLabel("<b>Pattern generator</b>  mode:"))
        self.sel_mode = QComboBox()
        self.sel_mode.addItems(["duty", "booster", "custom"])
        pg_bar.addWidget(self.sel_mode)
        pg_bar.addWidget(QLabel("duty:"))
        self.sp_duty = QDoubleSpinBox()
        self.sp_duty.setRange(0.0, 1.0)
        self.sp_duty.setSingleStep(0.05)
        self.sp_duty.setValue(0.4)
        pg_bar.addWidget(self.sp_duty)
        pg_bar.addWidget(QLabel("turn:"))
        self.sp_turn = QSpinBox(); self.sp_turn.setRange(20, 2048)
        self.sp_turn.setValue(306); pg_bar.addWidget(self.sp_turn)
        pg_bar.addWidget(QLabel("notch:"))
        self.sp_notch = QSpinBox(); self.sp_notch.setRange(0, 512)
        self.sp_notch.setValue(60); pg_bar.addWidget(self.sp_notch)
        pg_bar.addWidget(QLabel("custom:"))
        self.ed_pat = QLineEdit("1111000000")
        self.ed_pat.setMaximumWidth(220)
        pg_bar.addWidget(self.ed_pat)
        self.btn_pat = QPushButton("Program")
        pg_bar.addWidget(self.btn_pat)
        self.lbl_verify = QLabel("")
        pg_bar.addWidget(self.lbl_verify, 1)
        self.body.addLayout(pg_bar)

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
        self.btn_pat.clicked.connect(self._program)
        self.hub.wcm.connect(self._on_wcm)
        # programmed-pattern overlay on the bucket bars
        self.pat_marks = self.p_bar.plot(
            pen=None, symbol="o", symbolSize=5, symbolBrush=None,
            symbolPen=pg.mkPen("#4fc3f7", width=1.2), name="programmed")

    def _program(self):
        m = self.sel_mode.currentText()
        for f, v in (("mode", m), ("duty", self.sp_duty.value()),
                     ("turn", self.sp_turn.value()),
                     ("notch", self.sp_notch.value()),
                     ("pattern", self.ed_pat.text().strip() or "1")):
            self.hub.set_setting("chopper", "main", f, v)

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
        # programmed pattern overlay + verification readout
        pat = data.get("pat")
        if pat is not None:
            on = np.nonzero(np.asarray(pat) > 0.5)[0]
            top = (np.log10(np.maximum(q, 1e-7)) + 7).max() \
                if self.chk_log.isChecked() else max(q.max(), 1e-9)
            self.pat_marks.setData(on, np.full(len(on), top * 1.06))
        v = {k.decode(): x.decode() for k, x in
             self.hub.r.hgetall("state:bpg").items()}
        if v:
            mm = int(v.get("mismatch_buckets", 0))
            ok = "✓ pattern verified" if mm == 0 else \
                 f"✗ {mm} buckets differ from programmed!"
            col = "#2ecc71" if mm == 0 else "#e74c3c"
            self.lbl_verify.setText(
                f"<span style='color:{col}'>{ok}</span>  "
                f"(mode {v.get('mode','duty')}, programmed duty "
                f"{v.get('programmed_duty','?')}, measured "
                f"{v.get('measured_duty','?')})")

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
