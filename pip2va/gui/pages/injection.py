"""Booster injection — the machine's figure of merit, its diagnostics, and
the painting / debuncher knobs that drive it."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit)
from PyQt6.QtCore import QTimer

from .. import theme
from ..widgets import BigValue
from . import register
from .common import Page, make_plot

_DESC = """
<b>Booster injection</b> is the machine's real figure of merit — protons
usefully painted into the Booster per pulse, scored 0–100. It is computed
every pulse from the <i>real</i> delivered beam (normalised emittance and
momentum spread from the envelope) plus the injection knobs. Three effects
set the optimum:
<ul>
<li><b>RF bucket capture</b> — momentum tails outside the Booster
adiabatic-capture acceptance (±0.3%) are lost. Squeeze <b>dp/p</b> with the
BTL <b>debunchers</b> to raise capture.</li>
<li><b>Space-charge tune shift ΔQ_sc</b> (Laslett) — the PIP-II design
driver. Painting spreads the beam to a larger emittance to keep ΔQ below the
~0.35 resonance limit. Too dense → ΔQ over limit → loss; too diffuse →
overflows the acceptance.</li>
<li><b>Foil hits</b> — protons re-traverse the foil while the injection bump
overlaps it, adding emittance (multiple scattering) and heating it. Faster
bump decay + adequate bump amplitude → fewer hits (budget &lt; ~6).</li>
</ul>
Levers: the <b>debunchers</b> (dp/p → capture), the <b>painting bump</b> and
<b>decay</b> (space charge, foil hits, acceptance), and upstream match /
steering (emittance, orbit at the foil).
"""


@register("Booster Injection")
class InjectionPage(Page):
    title = "Booster Injection"

    def build(self):
        # ---- headline values
        top = QHBoxLayout()
        self.v_score = BigValue("Injection η", "score", "{:.1f}")
        self.v_cap = BigValue("Bucket capture", "", "{:.2f}")
        self.v_dq = BigValue("ΔQ space-charge", "/ 0.35", "{:.3f}")
        self.v_hits = BigValue("Foil hits", "/ 6", "{:.1f}")
        self.v_prot = BigValue("Protons / pulse", "", "{:.2e}")
        for w in (self.v_score, self.v_cap, self.v_dq, self.v_hits,
                  self.v_prot):
            top.addWidget(w)
        self.body.addLayout(top)

        self.lbl_diag = QLabel("—")
        self.lbl_diag.setStyleSheet("color:#8b96a5;")
        self.body.addWidget(self.lbl_diag)

        # ---- score history
        self.p_hist = make_plot("injection η", xlabel="samples")
        self.p_hist.setTitle("Injection score history")
        self.c_hist = self.p_hist.plot(pen=pg.mkPen(theme.ACCENT, width=2))
        self.p_hist.addLine(y=60, pen=pg.mkPen(theme.WARN,
                            style=pg.QtCore.Qt.PenStyle.DashLine))
        self.body.addWidget(self.p_hist, 1)
        self.hist = collections.deque(maxlen=400)

        # ---- knobs: painting + debunchers
        ctl = QGridLayout()
        ctl.addWidget(QLabel("<b>Painting</b>"), 0, 0)
        ctl.addWidget(QLabel("bump [mm]"), 0, 1)
        self.sp_bump = QDoubleSpinBox()
        self.sp_bump.setRange(0.5, 25.0)
        self.sp_bump.setValue(8.0)
        ctl.addWidget(self.sp_bump, 0, 2)
        ctl.addWidget(QLabel("decay [turns]"), 0, 3)
        self.sp_decay = QDoubleSpinBox()
        self.sp_decay.setRange(5.0, 285.0)
        self.sp_decay.setValue(12.0)
        ctl.addWidget(self.sp_decay, 0, 4)
        b_paint = QPushButton("Apply painting")
        b_paint.clicked.connect(lambda: (
            self.hub.set_setting("injection", "main", "bump0_mm",
                                 self.sp_bump.value()),
            self.hub.set_setting("injection", "main", "decay_turns",
                                 self.sp_decay.value())))
        ctl.addWidget(b_paint, 0, 5)

        ctl.addWidget(QLabel("<b>Debunchers</b>"), 1, 0)
        ctl.addWidget(QLabel("amp [MV]"), 1, 1)
        self.sp_damp = QDoubleSpinBox()
        self.sp_damp.setRange(0.0, 3.0)
        self.sp_damp.setValue(1.3)
        ctl.addWidget(self.sp_damp, 1, 2)
        ctl.addWidget(QLabel("phase [deg]"), 1, 3)
        self.sp_dph = QDoubleSpinBox()
        self.sp_dph.setRange(-180.0, 180.0)
        self.sp_dph.setValue(90.0)
        ctl.addWidget(self.sp_dph, 1, 4)
        b_deb = QPushButton("Apply debunchers")
        b_deb.clicked.connect(self._apply_debunchers)
        ctl.addWidget(b_deb, 1, 5)
        self.body.addLayout(ctl)

        desc = QTextEdit()
        desc.setReadOnly(True)
        desc.setHtml(_DESC)
        desc.setMaximumHeight(200)
        self.body.addWidget(desc)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(500)

    def _apply_debunchers(self):
        for nm in ("BTL:CAV1", "BTL:CAV2"):
            self.hub.set_setting("rf", nm, "amp", self.sp_damp.value())
            self.hub.set_setting("rf", nm, "phase", self.sp_dph.value())

    def _poll(self):
        if not self.isVisible():
            return
        raw = self.hub.r.hgetall("state:injection")
        if not raw:
            return
        d = {k.decode(): float(v) for k, v in raw.items()}
        sc = d.get("score", 0.0)
        self.v_score.set(sc, theme.OK if sc > 60 else theme.WARN)
        self.v_cap.set(d.get("capture_eff", 0.0))
        dq = d.get("dq_sc", 0.0)
        self.v_dq.set(dq, theme.ALARM if dq > 0.35 else theme.OK)
        hits = d.get("foil_hits", 0.0)
        self.v_hits.set(hits, theme.ALARM if hits > 6 else theme.OK)
        self.v_prot.set(d.get("protons_per_pulse", 0.0))
        self.lbl_diag.setText(
            f"injected εₙ = {d.get('eps_inj_um', 0):.2f} mm·mrad   →   "
            f"painted εₙ = {d.get('eps_paint_um', 0):.2f} mm·mrad   |   "
            f"space-charge loss = {100 * d.get('sc_loss_frac', 0):.1f}%   |   "
            f"acceptance fit = {100 * d.get('accept_frac', 0):.0f}%")
        self.hist.append(sc)
        self.c_hist.setData(np.fromiter(self.hist, float))
