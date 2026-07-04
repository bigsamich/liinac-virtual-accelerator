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
        from PyQt6.QtWidgets import QSpinBox
        self.spin_pts = QSpinBox()
        self.spin_pts.setRange(8, 256)
        self.spin_pts.setValue(64)
        self.spin_pts.setToolTip("number of wire positions in the scan")
        self.spin_ppp = QSpinBox()
        self.spin_ppp.setRange(1, 20)
        self.spin_ppp.setValue(1)
        self.spin_ppp.setToolTip("pulses the wire dwells at each position")
        bar.addWidget(QLabel("Scanner:"))
        bar.addWidget(self.sel_ws)
        bar.addWidget(QLabel("points:"))
        bar.addWidget(self.spin_pts)
        bar.addWidget(QLabel("pulses/pt:"))
        bar.addWidget(self.spin_ppp)
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

        # 3D beam cloud at a scanner station (GPU tracker, GL scatter)
        cloud_bar = QHBoxLayout()
        cloud_bar.addWidget(QLabel("3D beam cloud at:"))
        self.sel_3d = QComboBox()
        self.sel_3d.addItems(self.wss)
        cloud_bar.addWidget(self.sel_3d)
        self.lbl_3d = QLabel("")
        self.lbl_3d.setStyleSheet("color:#8b96a5;")
        cloud_bar.addWidget(self.lbl_3d)
        cloud_bar.addStretch(1)
        self.body.addLayout(cloud_bar)
        self.gl_view = None
        try:
            import pyqtgraph.opengl as gl
            self.gl = gl
            self.gl_view = gl.GLViewWidget()
            self.gl_view.setMinimumHeight(260)
            self.gl_view.setCameraPosition(distance=40, elevation=18)
            grid = gl.GLGridItem()
            grid.scale(2, 2, 1)
            self.gl_view.addItem(grid)
            self.gl_scatter = gl.GLScatterPlotItem(size=1.5, pxMode=True)
            self.gl_view.addItem(self.gl_scatter)
            self.body.addWidget(self.gl_view, 3)
        except Exception as e:               # headless / no OpenGL context
            self.body.addWidget(QLabel(f"3D view unavailable: {e}"))
        self.sel_3d.currentTextChanged.connect(self.hub.select_3d_station)
        if self.wss:
            self.hub.select_3d_station(self.sel_3d.currentText())

        # emittance vs s from the deep pass
        self.p_emit = make_plot("εₙ [µm]", xlabel="s [m]")
        self.c_ex = self.p_emit.plot(pen=pg.mkPen(theme.ACCENT, width=1.5),
                                     name="εx")
        self.c_ey = self.p_emit.plot(pen=pg.mkPen("#ffb74d", width=1.5),
                                     name="εy")
        self.p_emit.addLegend(offset=(6, 6))
        self.body.addWidget(self.p_emit, 1)

        self.btn_scan.clicked.connect(
            lambda: self.hub.request_wire_scan(
                self.sel_ws.currentText(), points=self.spin_pts.value(),
                ppp=self.spin_ppp.value()))
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
        cloud = data.get("cloud")
        if cloud is not None:
            self._last_cloud = (cloud, data.get("cloud_at", "?"))
        elif self.gl_view is not None and not getattr(self, "_last_cloud", None):
            self.lbl_3d.setText("waiting for next GPU pass (~3 s)…")
        if cloud is not None and self.gl_view is not None:
            self._render_cloud(cloud, data.get("cloud_at", "?"))

    def showEvent(self, ev):
        super().showEvent(ev)
        # re-assert the station (service may have restarted) and re-render
        if self.wss:
            self.hub.select_3d_station(self.sel_3d.currentText())
        lc = getattr(self, "_last_cloud", None)
        if lc and self.gl_view is not None:
            self._render_cloud(*lc)

    def _render_cloud(self, cloud, station):
        try:
            pts = np.array(cloud, dtype=np.float32).T.copy()  # (n, 3) mm
            # normalize z (bunch length) to the transverse scale for display
            span = max(float(np.abs(pts[:, :2]).max()), 1e-3)
            zspan = max(float(np.abs(pts[:, 2]).max()), 1e-3)
            pts[:, 2] *= span / zspan
            r = np.linalg.norm(pts[:, :2], axis=1) / span
            colors = np.empty((len(pts), 4), dtype=np.float32)
            colors[:, 0] = 0.31 + 0.6 * r          # core cyan -> halo warm
            colors[:, 1] = 0.76 - 0.35 * r
            colors[:, 2] = 0.97 - 0.55 * r
            colors[:, 3] = 0.55
            self.gl_scatter.setData(pos=pts * (10.0 / span), color=colors)
            self.lbl_3d.setText(
                f"{station} — {len(pts):,} particles "
                f"(z stretched ×{span/zspan:.2g} for display; drag to rotate)")
        except Exception as e:   # runtime GL failure: degrade gracefully
            self.lbl_3d.setText(f"3D render failed: {e}")
            self.gl_view = None
