"""Machine dashboard: synoptic overview + instrumentation in one page."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit)

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
        row2.addWidget(self.p_orbit, 1)
        self.p_loss = CrosshairPlot("loss [W/m]", device_names=self.blm_names,
                                    log_y=True)
        self.loss_bars = pg.BarGraphItem(x=np.arange(len(blms)),
                                         height=np.zeros(len(blms)),
                                         width=0.7, brush=theme.WARN)
        self.p_loss.addItem(self.loss_bars)
        self.p_loss.pw.setYRange(-3.2, 1.0)
        row2.addWidget(self.p_loss, 1)
        self.body.addLayout(row2, 3)

        # toroid strip chart + per-boundary transmission
        self.tors = lat.instruments("toroid")
        row3 = QHBoxLayout()
        self.p_tor = CrosshairPlot("I [mA]", xlabel="pulse")
        cmap = pg.colormap.get("CET-C6s")
        self.tor_curves = []
        for k, t in enumerate(self.tors):
            pen = pg.mkPen(cmap.map(k / max(len(self.tors) - 1, 1),
                                    mode="qcolor"), width=1.4)
            self.tor_curves.append(self.p_tor.plot(pen=pen, name=t.name))
        self.p_tor.addLegend(offset=(6, 6), labelTextSize="8pt")
        row3.addWidget(self.p_tor, 2)
        self.p_bars = CrosshairPlot("boundary T [%]", xlabel="")
        self.t_bars = pg.BarGraphItem(x=np.arange(len(self.tors) - 1),
                                      height=np.zeros(len(self.tors) - 1),
                                      width=0.6, brush=theme.ACCENT)
        self.p_bars.addItem(self.t_bars)
        ax = self.p_bars.pw.getAxis("bottom")
        ax.setTicks([[(k, f"{self.tors[k].section}→{self.tors[k+1].section}")
                      for k in range(len(self.tors) - 1)]])
        self.p_bars.pw.setYRange(0, 112)
        row3.addWidget(self.p_bars, 2)
        row3.setStretch(0, 2)
        self.body.addLayout(row3, 2)

        self.lbl_health = QLabel("device health: —")
        self.body.addWidget(self.lbl_health)

        # ---- ask the machine: LLM Q&A grounded in live state + study KB
        ask_row = QHBoxLayout()
        self.ed_ask = QLineEdit()
        self.ed_ask.setPlaceholderText(
            "Ask the machine… (status? what happens if I raise the source "
            "to 6 mA? can I run unchopped? why is BTL:BLM1 high?)")
        self.btn_ask = QPushButton("Ask")
        ask_row.addWidget(self.ed_ask, 1)
        ask_row.addWidget(self.btn_ask)
        self.body.addLayout(ask_row)
        self.txt_answer = QTextEdit()
        self.txt_answer.setReadOnly(True)
        self.txt_answer.setMaximumHeight(140)
        self.txt_answer.setPlaceholderText(
            "Answers combine the live snapshot with measured findings from "
            "the machine's own beam studies.")
        self.txt_answer.hide()
        self.body.addWidget(self.txt_answer)
        self.btn_ask.clicked.connect(self._ask)
        self.ed_ask.returnPressed.connect(self._ask)
        self._ask_worker = None

    def _ask(self):
        q = self.ed_ask.text().strip()
        if not q or (self._ask_worker and self._ask_worker.isRunning()):
            return
        self.txt_answer.show()
        self.txt_answer.setPlainText("thinking…")
        self.btn_ask.setEnabled(False)
        self._ask_worker = AskWorker(self.hub.r, q)
        self._ask_worker.done.connect(self._answered)
        self._ask_worker.start()

    def _answered(self, text, engine):
        self.btn_ask.setEnabled(True)
        self.txt_answer.setPlainText(f"[{engine}]\n{text}")

        self.t_hist = [collections.deque(maxlen=400) for _ in self.tors]
        self._rf_index = None
        self._rf_trips = 0
        self._mag_trips = 0
        self._gate = 0
        self.pulse_ms = lat.meta.get("beam_ms", 0.54)
        self.hub.beamState.connect(self._on_state)
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

    def _on_losses(self, _pid, data):
        if not self.isVisible():
            return
        w = data["wpm"]
        mx = float(np.max(w)) if len(w) else 0.0
        self.v_loss.set(mx, theme.OK if mx < 1.0 else theme.ALARM)
        if self._gate % 4 == 0:
            self.loss_bars.setOpts(height=np.maximum(w, 1e-4))

    def _on_toroids(self, _pid, data):
        if not self.isVisible():
            return
        i = data["i_ma"]
        n = min(len(i), len(self.t_hist))
        for k in range(n):
            self.t_hist[k].append(float(i[k]))
        if self._gate % 4 == 0:
            for k in range(n):
                self.tor_curves[k].setData(
                    np.arange(len(self.t_hist[k])),
                    np.fromiter(self.t_hist[k], float))
            self.p_tor.update_y(i)
        if n >= 3:
            self.v_i.set(float(i[-1]))
            self.v_charge.set(float(i[-1]) * 1e-3 * self.pulse_ms * 1e3)
            r = np.maximum(i[:-1], 1e-6)
            self.t_bars.setOpts(height=np.clip(100.0 * i[1:] / r, 0, 110))

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


class AskWorker(QThread):
    done = pyqtSignal(str, str)

    def __init__(self, r, question):
        super().__init__()
        self.r, self.q = r, question

    def run(self):
        try:
            from pip2va.analysis import assistant
            text, engine = assistant.ask(self.r, self.q)
            self.done.emit(text, engine)
        except Exception as e:
            self.done.emit(f"assistant error: {e}", "error")
