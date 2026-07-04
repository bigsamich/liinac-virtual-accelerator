"""Ion source, LEBT, and chopper controls."""
from __future__ import annotations

import collections

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
                             QLabel, QVBoxLayout)

from .. import theme
from . import register
from .common import Page, make_plot


@register("Source & LEBT")
class SourcePage(Page):
    title = "Ion Source, LEBT & Chopper"

    def build(self):
        top = QHBoxLayout()

        # source + chopper controls
        ctl = QFrame()
        ctl.setObjectName("panel")
        form = QFormLayout(ctl)
        self.spin_i = QDoubleSpinBox()
        self.spin_i.setRange(0.0, 15.0)
        self.spin_i.setDecimals(2)
        self.spin_i.setSingleStep(0.25)
        st = self.hub.get_settings("source", "main")
        self.spin_i.setValue(float(st.get("current_ma", 5.0)))
        self.spin_i.valueChanged.connect(
            lambda v: self.hub.set_setting("source", "main", "current_ma", v))
        form.addRow("Source current [mA]", self.spin_i)

        self.spin_duty = QDoubleSpinBox()
        self.spin_duty.setRange(0.0, 1.0)
        self.spin_duty.setDecimals(2)
        self.spin_duty.setSingleStep(0.05)
        stc = self.hub.get_settings("chopper", "main")
        self.spin_duty.setValue(float(stc.get(
            "duty", 1.0 - self.lat.meta.get("chop_fraction", 0.6))))
        self.spin_duty.valueChanged.connect(self._on_duty)
        form.addRow("Chopper keep-fraction", self.spin_duty)

        self.sols = [e for e in self.lat.elements
                     if e.type == "solenoid" and e.section == "LEBT"]
        for el in self.sols:
            sp = QDoubleSpinBox()
            sp.setRange(-500, 500)
            sp.setDecimals(2)
            sset = self.hub.get_settings("magnet", el.name)
            sp.setValue(float(sset.get("current",
                                       el.params["design_current"])))
            sp.valueChanged.connect(
                lambda v, el=el: self.hub.set_setting(
                    "magnet", el.name, "current", v))
            form.addRow(f"{el.name} [A]", sp)
        top.addWidget(ctl, 1)

        # pulse structure preview
        prev = QVBoxLayout()
        prev.addWidget(QLabel("Pulse structure preview (0.55 ms window)"))
        self.p_pulse = make_plot("I [mA]", xlabel="t [ms]")
        self.c_pulse = self.p_pulse.plot(
            pen=pg.mkPen(theme.ACCENT, width=2), fillLevel=0.0,
            brush=pg.mkBrush(79, 195, 247, 60))
        prev.addWidget(self.p_pulse)
        top.addLayout(prev, 2)
        self.body.addLayout(top, 1)

        # LEBT/MEBT toroid strip
        self.p_tor = make_plot("I [mA]", xlabel="pulse")
        self.c_t0 = self.p_tor.plot(pen=pg.mkPen(theme.ACCENT, width=1.5),
                                    name="LEBT")
        self.c_t1 = self.p_tor.plot(pen=pg.mkPen("#ffb74d", width=1.5),
                                    name="MEBT out")
        self.p_tor.addLegend(offset=(6, 6))
        self.body.addWidget(self.p_tor, 1)

        self.h0 = collections.deque(maxlen=400)
        self.h1 = collections.deque(maxlen=400)
        self.hub.toroids.connect(self._on_toroids)
        self._draw_pulse()

    def _on_duty(self, v):
        self.hub.set_setting("chopper", "main", "duty", v)
        self._draw_pulse()

    def _draw_pulse(self):
        """Chopped 44.7 MHz-bucket pattern rendered at display resolution."""
        duty = self.spin_duty.value()
        i0 = self.spin_i.value()
        t = np.linspace(0, 0.55, 1200)
        beam = (t < 0.54).astype(float) * i0
        # visualize chopping as a fast bucket comb (display-scale, not 162.5 MHz)
        comb = (np.sin(2 * np.pi * t * 200) + 1) / 2 < duty
        self.c_pulse.setData(t, beam * comb)

    def _on_toroids(self, _pid, data):
        i = data["i_ma"]
        if len(i) >= 3:
            self.h0.append(float(i[0]))
            self.h1.append(float(i[2]))
            self.c_t0.setData(np.arange(len(self.h0)),
                              np.fromiter(self.h0, float))
            self.c_t1.setData(np.arange(len(self.h1)),
                              np.fromiter(self.h1, float))
