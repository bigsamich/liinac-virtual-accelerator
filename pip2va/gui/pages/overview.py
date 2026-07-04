"""Synoptic machine overview: the landing page."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QHBoxLayout

from .. import theme
from ..widgets import BigValue, SectionStrip
from . import register
from .common import Page, add_section_shading, make_plot


@register("Overview")
class OverviewPage(Page):
    title = "PIP-II Linac — Synoptic Overview"

    def build(self):
        lat = self.lat
        self.strip = SectionStrip([s.name for s in lat.sections])
        self.strip.sectionClicked.connect(self._goto_section)
        self.body.addWidget(self.strip)

        row = QHBoxLayout()
        self.v_w = BigValue("Output energy", "MeV", "{:.1f}")
        self.v_t = BigValue("Transmission", "%", "{:.2f}")
        self.v_i = BigValue("Beam current (BTL)", "mA", "{:.3f}")
        self.v_loss = BigValue("Worst BLM", "W/m", "{:.3f}")
        self.v_pulse = BigValue("Pulse", "", "{:.0f}")
        for v in (self.v_w, self.v_t, self.v_i, self.v_loss, self.v_pulse):
            row.addWidget(v)
        self.body.addLayout(row)

        # design energy profile with measured end-point marker
        self.p_w = make_plot("W [MeV]")
        add_section_shading(self.p_w, lat)
        s_pts, w_pts = [], []
        for sec in lat.sections:
            s_pts += [sec.s_start, sec.s_end]
            w_pts += [sec.w_in, sec.w_out]
        self.p_w.plot(s_pts, w_pts, pen=pg.mkPen(theme.ACCENT, width=2))
        self.body.addWidget(self.p_w, 2)

        # transmission history strip
        self.p_t = make_plot("T [%]", xlabel="pulse")
        self.t_hist = collections.deque(maxlen=600)
        self.t_curve = self.p_t.plot(pen=pg.mkPen(theme.OK, width=2))
        self.body.addWidget(self.p_t, 1)

        self.hub.beamState.connect(self._on_state)
        self.hub.losses.connect(self._on_losses)
        self.hub.toroids.connect(self._on_toroids)
        self.hub.rf.connect(self._on_rf)
        self._rf_index = None
        self._tor_i = None

    def _goto_section(self, name):
        w = self.window()
        if hasattr(w, "goto"):
            w.goto({"LEBT": "Source & LEBT", "RFQ": "RF",
                    "MEBT": "Magnets"}.get(name, "Orbit"))

    def _on_state(self, st):
        if not st:
            return
        self.v_w.set(st.get("w_out", 0.0))
        t = 100.0 * st.get("transmission", 0.0)
        self.v_t.set(t, theme.OK if t > 95 else theme.ALARM)
        self.v_pulse.set(st.get("pulse_id", 0))
        self.t_hist.append(t)
        self.t_curve.setData(np.arange(len(self.t_hist)),
                             np.fromiter(self.t_hist, float))

    def _on_losses(self, _pid, data):
        w = float(np.max(data["wpm"])) if len(data["wpm"]) else 0.0
        self.v_loss.set(w, theme.OK if w < 1.0 else theme.ALARM)

    def _on_toroids(self, _pid, data):
        i = data["i_ma"]
        if len(i):
            self.v_i.set(float(i[-1]))

    def _on_rf(self, _pid, data):
        if self._rf_index is None:
            self._rf_index = self.hub.get_index("rf")
        if not self._rf_index:
            return
        bad_secs = {self._rf_index[j].split(":")[0]
                    for j in np.nonzero(data["status"] > 0.5)[0]
                    if j < len(self._rf_index)}
        for sec in self.strip.buttons:
            self.strip.set_health(sec, sec not in bad_secs)
