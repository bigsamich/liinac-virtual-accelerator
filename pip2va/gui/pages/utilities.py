"""Utilities & bunch monitor: cryoplant 2 K pressures, LCW temperature,
their electronics couplings, and the RWCM bunch-by-bunch viewer."""
from __future__ import annotations

import collections
import json

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                             QHBoxLayout, QLabel, QPushButton)

from .. import theme
from ..plotkit import CrosshairPlot
from . import register
from .common import Page


@register("Utilities")
class UtilitiesPage(Page):
    title = "Utilities — cryo, LCW & bunch monitor"

    def build(self):
        from pip2va.services.timing.utilities import (CRYOMODULES,
                                                      LCW_NOM_C, P_NOM_MBAR)
        self.cm_names = [c[0] for c in CRYOMODULES]
        self.p_nom, self.lcw_nom = P_NOM_MBAR, LCW_NOM_C

        top = QHBoxLayout()
        self.lbl_lcw = QLabel("LCW: — °C")
        self.lbl_lcw.setStyleSheet("font-size: 15px; font-weight: bold;")
        top.addWidget(self.lbl_lcw)
        self.lbl_fx = QLabel("")
        top.addWidget(self.lbl_fx, 1)
        # fault injection: plant offsets
        top.addWidget(QLabel("inject: LCW +"))
        self.sp_lcw = QDoubleSpinBox()
        self.sp_lcw.setRange(-5, 10)
        self.sp_lcw.setSingleStep(0.5)
        self.sp_lcw.setSuffix(" °C")
        top.addWidget(self.sp_lcw)
        top.addWidget(QLabel("  cryo"))
        self.sel_cm = QComboBox()
        self.sel_cm.addItems(self.cm_names)
        top.addWidget(self.sel_cm)
        self.sp_cryo = QDoubleSpinBox()
        self.sp_cryo.setRange(-5, 10)
        self.sp_cryo.setSingleStep(0.2)
        self.sp_cryo.setSuffix(" mbar")
        top.addWidget(self.sp_cryo)
        self.btn_apply = QPushButton("Apply")
        self.btn_clear = QPushButton("Clear")
        top.addWidget(self.btn_apply)
        top.addWidget(self.btn_clear)
        self.body.addLayout(top)

        row = QHBoxLayout()
        self.p_lcw = CrosshairPlot("LCW supply [°C]", xlabel="sample")
        self.c_lcw = self.p_lcw.plot(pen=pg.mkPen(theme.ACCENT, width=1.5),
                                     name="LCW")
        row.addWidget(self.p_lcw, 1)
        self.p_cryo = CrosshairPlot("2 K bath [mbar]", xlabel="")
        self.cryo_bars = pg.BarGraphItem(
            x=np.arange(len(self.cm_names)),
            height=np.zeros(len(self.cm_names)), width=0.65,
            brush=theme.ACCENT)
        self.p_cryo.addItem(self.cryo_bars)
        ax = self.p_cryo.pw.getAxis("bottom")
        ax.setTicks([[(k, n.replace("CM-", ""))
                      for k, n in enumerate(self.cm_names)]])
        self.p_cryo.pw.setYRange(self.p_nom - 1.0, self.p_nom + 1.0)
        row.addWidget(self.p_cryo, 2)
        self.body.addLayout(row, 2)

        self._lcw_hist = collections.deque(maxlen=600)
        self._gate = 0
        self.btn_apply.clicked.connect(self._apply)
        self.btn_clear.clicked.connect(self._clear)
        self.hub.beamState.connect(self._on_state)

    # ------------------------------------------------------------- controls

    def _apply(self):
        self.hub.set_setting("util", "main", "lcw_offset_c",
                             self.sp_lcw.value())
        self.hub.set_setting("util", "main", "cryo_offset_mbar",
                             self.sp_cryo.value())
        self.hub.set_setting("util", "main", "cryo_cm",
                             self.sel_cm.currentText())

    def _clear(self):
        self.sp_lcw.setValue(0.0)
        self.sp_cryo.setValue(0.0)
        self._apply()

    # ------------------------------------------------------------ live data

    def _on_state(self, st):
        if not self.isVisible():
            return
        self._gate += 1
        if self._gate % 10:
            return
        u = self.hub.r.get("state:util")
        if not u:
            return
        try:
            d = json.loads(u)
        except ValueError:
            return
        lcw = d.get("lcw_c", self.lcw_nom)
        self._lcw_hist.append(lcw)
        dT = lcw - self.lcw_nom
        col = theme.OK if abs(dT) < 1.0 else theme.ALARM
        self.lbl_lcw.setText(f"LCW: {lcw:.2f} °C")
        self.lbl_lcw.setStyleSheet(
            f"font-size:15px; font-weight:bold; color:{col};")
        self.lbl_fx.setText(
            f"couplings — BPM phase {0.033 * dT:+.3f}°, TOF energy "
            f"{0.06 * dT:+.2f} MeV class, SSA cal {-0.4 * dT:+.2f}%   |   "
            f"cryo df/dp: SSR2 ≈ −2.6 Hz/mbar, HB650 ≈ −19 Hz/mbar")
        arr = np.fromiter(self._lcw_hist, float)
        self.c_lcw.setData(np.arange(len(arr)), arr)
        self.p_lcw.update_y(arr)
        pm = d.get("p_mbar", {})
        self.cryo_bars.setOpts(
            height=[pm.get(n, self.p_nom) for n in self.cm_names])
