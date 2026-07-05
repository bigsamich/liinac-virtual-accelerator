"""Machine dashboard: synoptic overview + instrumentation in one page."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QHBoxLayout, QLabel

from .. import theme
from ..plotkit import CrosshairPlot
from ..widgets import BigValue, SectionStrip
from . import register
from .common import Page


@register("Dashboard")
class OverviewPage(Page):
    title = "PIP-II Linac — Dashboard"

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
        self.v_charge = BigValue("Pulse charge", "µC", "{:.3f}")
        self.v_pulse = BigValue("Pulse", "", "{:.0f}")
        for v in (self.v_w, self.v_t, self.v_i, self.v_loss,
                  self.v_charge, self.v_pulse):
            row.addWidget(v)
        self.body.addLayout(row)

        # live orbit + losses at a glance
        bpms = lat.instruments("bpm")
        blms = lat.instruments("blm")
        self.bpm_names = [e.name for e in bpms]
        self.blm_names = [e.name for e in blms]
        row2 = QHBoxLayout()
        self.p_orbit = CrosshairPlot("orbit x/y [mm]",
                                     device_names=self.bpm_names)
        self.c_ox = self.p_orbit.plot(pen=pg.mkPen(theme.ACCENT, width=1),
                                      name="x")
        self.c_oy = self.p_orbit.plot(pen=pg.mkPen("#ffb74d", width=1),
                                      name="y")
        self.p_orbit.addLegend(offset=(6, 6), labelTextSize="8pt")
        row2.addWidget(self.p_orbit, 2)
        self.p_loss = CrosshairPlot("", xlabel="loss [W/m]")
        self.loss_bars = pg.BarGraphItem(
            x0=0, y=np.arange(len(blms)), height=0.75,
            width=np.zeros(len(blms)), brush=theme.WARN)
        self.p_loss.addItem(self.loss_bars)
        secs = []
        seen = set()
        for j, b in enumerate(blms):
            if b.section not in seen:
                seen.add(b.section)
                secs.append((j, b.section))
        self.p_loss.pw.getAxis("left").setTicks([secs])
        self.p_loss.pw.invertY(True)         # LEBT top, BTL bottom
        self.p_loss.pw.setYRange(-1, len(blms))
        self.p_loss.pw.setXRange(0, 30)
        row2.addWidget(self.p_loss, 1)

        # vertical BCM histogram (LEBT top -> BTL bottom), next to BLM
        self.tors = lat.instruments("toroid")
        self.p_bcm = CrosshairPlot("", xlabel="beam current [mA]")
        self.bcm_bars = pg.BarGraphItem(
            x0=0, y=np.arange(len(self.tors)), height=0.6,
            width=np.zeros(len(self.tors)), brush=theme.ACCENT)
        self.p_bcm.addItem(self.bcm_bars)
        lax = self.p_bcm.pw.getAxis("left")
        lax.setTicks([[(k, f"{t.section}:{t.name.split(':')[1]}")
                       for k, t in enumerate(self.tors)]])
        self.p_bcm.pw.invertY(True)          # LEBT on top, BTL on bottom
        self.p_bcm.pw.setXRange(0, 6.0)
        self.p_bcm.pw.setYRange(-0.7, len(self.tors) - 0.3)
        row2.addWidget(self.p_bcm, 1)

        from PyQt6.QtCore import Qt
        self.lbl_teff = QLabel("boundary transmission: —")
        self.lbl_teff.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_teff.setStyleSheet("font-size: 13px; padding: 2px;")
        self.body.addLayout(row2, 3)
        self.body.addWidget(self.lbl_teff)

        # 3D synoptic: full linac + BTL with live orbit/losses/current
        from ..linac3d import Linac3D
        self.view3d = Linac3D(lat)
        self._tor_s = np.array([t.s for t in self.tors])
        self.body.addWidget(self.view3d, 4)

        self.lbl_health = QLabel("device health: —")
        self.body.addWidget(self.lbl_health)


        self._rf_index = None
        self._rf_trips = 0
        self._mag_trips = 0
        self._gate = 0
        self.pulse_ms = lat.meta.get("beam_ms", 0.54)
        self.hub.beamState.connect(self._on_state)
        self.hub.deep.connect(self._on_deep3d)
        self.hub.losses.connect(self._on_losses)
        self.hub.toroids.connect(self._on_toroids)
        self.hub.orbit.connect(self._on_orbit)
        self.hub.rf.connect(self._on_rf)
        self.hub.magnets.connect(self._on_magnets)

    def _goto_section(self, name):
        w = self.window()
        if hasattr(w, "goto_section"):
            w.goto_section(name)

    # ------------------------------------------------------------ live data

    def _on_state(self, st):
        if not st or not self.isVisible():
            return
        self.v_w.set(st.get("w_out", 0.0))
        t = 100.0 * st.get("transmission", 0.0)
        self.v_t.set(t, theme.OK if t > 95 else theme.ALARM)
        self.v_pulse.set(st.get("pulse_id", 0))

    def _on_orbit(self, _pid, data):
        self._gate += 1
        if not self.isVisible() or self._gate % 4:
            return
        xs = np.arange(len(data["x"]), dtype=float)
        x_mm, y_mm = data["x"] * 1e3, data["y"] * 1e3
        self.c_ox.setData(xs, x_mm)
        self.c_oy.setData(xs, y_mm)
        self.p_orbit.update_y(x_mm, y_mm)
        self.view3d.update_orbit(x_mm, y_mm)

    def _on_deep3d(self, _pid, data):
        cloud = data.get("cloud")
        if cloud is not None and self.isVisible():
            st = self.hub.r.hget("settings:wf3d:main", "station")
            if st:
                self.view3d.update_cloud(cloud, st.decode())

    def _envelope3d(self):
        blob = self.hub.r.hget("truth:beam", "d")
        if blob is None:
            return
        from pip2va.common import codec
        _, tr = codec.unpack(blob)
        self.view3d.update_envelope(tr["cx"], tr["cy"],
                                    tr["sig_x"], tr["sig_y"])

    def _on_losses(self, _pid, data):
        if not self.isVisible():
            return
        w = data["wpm"]
        mx = float(np.max(w)) if len(w) else 0.0
        self.v_loss.set(mx, theme.OK if mx < 1.0 else theme.ALARM)
        if self._gate % 4 == 0:
            self.loss_bars.setOpts(width=np.maximum(w, 0.0))
            self.p_loss.pw.setXRange(0, max(10.0, float(mx) * 1.15))
            self.view3d.update_losses(w)
        if self._gate % 24 == 0:
            self._envelope3d()

    def _on_toroids(self, _pid, data):
        if not self.isVisible():
            return
        i = data["i_ma"]
        n = min(len(i), len(self.tors))
        if self._gate % 4 == 0:
            self.bcm_bars.setOpts(width=np.maximum(i[:n], 0.0))
            self.view3d.update_current(i[:n], self._tor_s[:n])
        if n >= 3:
            self.v_i.set(float(i[-1]))
            self.v_charge.set(float(i[-1]) * 1e-3 * self.pulse_ms * 1e3)
            if self._gate % 4 == 0:
                r = np.maximum(i[:-1], 1e-6)
                tt = np.clip(100.0 * i[1:] / r, 0, 110)
                parts = []
                for k in range(n - 1):
                    # chopper boundary legitimately removes beam
                    chop = "MEBT" in self.tors[k + 1].section
                    good = tt[k] > 95 or chop
                    c = theme.OK if good else theme.ALARM
                    parts.append(
                        f"{self.tors[k].section}→{self.tors[k+1].section} "
                        f"<span style='color:{c};font-weight:bold'>"
                        f"{tt[k]:.2f}%</span>")
                self.lbl_teff.setText(
                    "<b>boundary T:</b> &nbsp;" +
                    " &nbsp;|&nbsp; ".join(parts))

    def _on_rf(self, _pid, data):
        self._rf_trips = int(np.sum(data["status"] > 0.5))
        if self._rf_index is None:
            self._rf_index = self.hub.get_index("rf")
        if self._rf_index and self.isVisible():
            bad = {self._rf_index[j].split(":")[0]
                   for j in np.nonzero(data["status"] > 0.5)[0]
                   if j < len(self._rf_index)}
            for sec in self.strip.buttons:
                self.strip.set_health(sec, sec not in bad)
        self._health()

    def _on_magnets(self, _pid, data):
        self._mag_trips = int(np.sum(data["status"] > 0.5))
        self._health()

    def _health(self):
        if not self.isVisible():
            return
        ok = self._rf_trips == 0 and self._mag_trips == 0
        self.lbl_health.setText(
            f"device health: {'ALL OK' if ok else 'FAULTS PRESENT'} — "
            f"RF trips: {self._rf_trips}, magnet trips: {self._mag_trips}")
        self.lbl_health.setStyleSheet(
            f"color: {theme.OK if ok else theme.ALARM}; font-weight: bold;")


