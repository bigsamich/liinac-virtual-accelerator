"""Profiles & phase space: wire/laserwire scans + macroparticle snapshots."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton

from .. import theme
from . import register
from .common import Page, gauss_fit, make_plot


@register("Profiles")
class ProfilesPage(Page):
    title = "Profile Monitors & Phase Space"

    def build(self):
        self.wss = [e.name for e in self.lat.instruments("wire_scanner")]
        bar = QHBoxLayout()
        self.sel_ws = QComboBox()
        self.sel_ws.addItems(self.wss)
        self.btn_scan = QPushButton("Start scan")
        self.lbl_fit = QLabel("fit: —")
        bar.addWidget(QLabel("Scanner:"))
        bar.addWidget(self.sel_ws)
        bar.addWidget(self.btn_scan)
        bar.addStretch(1)
        bar.addWidget(self.lbl_fit)
        self.body.addLayout(bar)

        self.p_prof = make_plot("counts", xlabel="position [mm]")
        self.c_x = self.p_prof.plot(pen=pg.mkPen(theme.ACCENT, width=2),
                                    name="x")
        self.c_y = self.p_prof.plot(pen=pg.mkPen("#ffb74d", width=2),
                                    name="y")
        self.c_fit = self.p_prof.plot(
            pen=pg.mkPen(theme.OK, style=pg.QtCore.Qt.PenStyle.DashLine))
        self.p_prof.addLegend(offset=(6, 6))
        self.body.addWidget(self.p_prof, 2)

        # phase-space snapshots
        ps_bar = QHBoxLayout()
        self.sel_sec = QComboBox()
        self.sel_sec.addItems([s.name for s in self.lat.sections])
        self.sel_sec.setCurrentText("HB650")
        ps_bar.addWidget(QLabel("Phase space at end of:"))
        ps_bar.addWidget(self.sel_sec)
        ps_bar.addStretch(1)
        self.body.addLayout(ps_bar)

        imgs = QHBoxLayout()
        self.ps_items = {}
        for key, label in (("xxp", "x–x′"), ("yyp", "y–y′"), ("zd", "z–δ")):
            p = make_plot("", xlabel=label)
            item = pg.ImageItem(axisOrder="row-major")
            item.setLookupTable(pg.colormap.get("viridis").getLookupTable())
            p.addItem(item)
            imgs.addWidget(p, 1)
            self.ps_items[key] = item
        self.body.addLayout(imgs, 2)

        # emittance vs s from the deep pass
        self.p_emit = make_plot("εₙ [µm]", xlabel="s [m]")
        self.c_ex = self.p_emit.plot(pen=pg.mkPen(theme.ACCENT, width=1.5),
                                     name="εx")
        self.c_ey = self.p_emit.plot(pen=pg.mkPen("#ffb74d", width=1.5),
                                     name="εy")
        self.p_emit.addLegend(offset=(6, 6))
        self.body.addWidget(self.p_emit, 1)

        self.btn_scan.clicked.connect(
            lambda: self.hub.request_wire_scan(self.sel_ws.currentText()))
        self.hub.scan.connect(self._on_scan)
        self.hub.deep.connect(self._on_deep)

    def _on_scan(self, _pid, data):
        if data.get("name") != self.sel_ws.currentText():
            return
        pos, ix, iy = data["pos_mm"], data["ix"], data["iy"]
        self.c_x.setData(pos, ix)
        self.c_y.setData(pos, iy)
        if data.get("done"):
            _amp, mu, sig, fit = gauss_fit(np.asarray(pos), np.asarray(ix))
            self.c_fit.setData(pos, fit)
            self.lbl_fit.setText(f"fit: µ={mu:.2f} mm  σ={sig:.2f} mm")

    def _on_deep(self, _pid, data):
        sec = self.sel_sec.currentText()
        for key, item in self.ps_items.items():
            img = data.get(f"ps:{sec}:{key}")
            if img is not None:
                item.setImage(np.asarray(img), autoLevels=True)
        if "emit_s" in data and len(data["emit_s"]):
            self.c_ex.setData(data["emit_s"], data["emit_x_um"])
            self.c_ey.setData(data["emit_s"], data["emit_y_um"])
