"""Profiles & phase space: wire/laserwire scans + macroparticle snapshots."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,
                             QPushButton)

from .. import theme
from ..plotkit import CrosshairPlot
from . import register
from .common import Page, gauss_fit, make_plot


@register("Profiles")
class ProfilesPage(Page):
    title = "Profile Monitors & Phase Space"

    def build(self):
        self.wss = [e.name for e in self.lat.instruments("wire_scanner")]
        from pip2va.common.laserwire import stations as _lw
        self.lw_pos = dict(_lw(self.lat))
        self.lws = list(self.lw_pos)
        bar = QHBoxLayout()
        self.sel_ws = QComboBox()
        self.sel_ws.addItems(self.wss)
        self.sel_ws.insertSeparator(len(self.wss))
        self.sel_ws.addItems(self.lws)
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
        self.chk_halo = QCheckBox("halo mode (7σ, high stats)")
        bar.addWidget(self.chk_halo)
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
        self.ps_plots = {}
        for key, label in (("xxp", "x–x′"), ("yyp", "y–y′"), ("zd", "z–δ")):
            p = make_plot("", xlabel=label)
            item = pg.ImageItem(axisOrder="row-major")
            item.setLookupTable(pg.colormap.get("viridis").getLookupTable())
            p.addItem(item)
            imgs.addWidget(p, 1)
            self.ps_items[key] = item
            self.ps_plots[key] = p
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
            lambda: (self.hub.request_lw_scan if ":LW" in
                     self.sel_ws.currentText() else
                     self.hub.request_wire_scan)(
                self.sel_ws.currentText(),
                halo=1 if (self.chk_halo.isChecked() and ":LW" in
                           self.sel_ws.currentText()) else 0,
                points=self.spin_pts.value(),
                ppp=self.spin_ppp.value()))
        # ---- profiler cycle: all wires + all lasers, one at a time each
        from PyQt6.QtWidgets import QSpinBox
        cyc = QHBoxLayout()
        cyc.addWidget(QLabel("<b>Cycle scans</b>  wire pts:"))
        self.sp_wsp = QSpinBox(); self.sp_wsp.setRange(8, 256)
        self.sp_wsp.setValue(64); cyc.addWidget(self.sp_wsp)
        cyc.addWidget(QLabel("ppp:"))
        self.sp_wsq = QSpinBox(); self.sp_wsq.setRange(1, 20)
        self.sp_wsq.setValue(1); cyc.addWidget(self.sp_wsq)
        cyc.addWidget(QLabel("   laser pts:"))
        self.sp_lwp = QSpinBox(); self.sp_lwp.setRange(8, 256)
        self.sp_lwp.setValue(48); cyc.addWidget(self.sp_lwp)
        cyc.addWidget(QLabel("ppp:"))
        self.sp_lwq = QSpinBox(); self.sp_lwq.setRange(1, 20)
        self.sp_lwq.setValue(1); cyc.addWidget(self.sp_lwq)
        self.btn_cycle = QPushButton("Start cycle")
        self.btn_cyc_stop = QPushButton("Stop")
        cyc.addWidget(self.btn_cycle)
        cyc.addWidget(self.btn_cyc_stop)
        self.lbl_cycle = QLabel("")
        cyc.addWidget(self.lbl_cycle, 1)
        self.body.addLayout(cyc)

        # sigma(s) from the last completed cycle: lasers vs wires
        self.p_sig = CrosshairPlot("rms size [mm]", xlabel="s [m]")
        self.c_lwx = self.p_sig.plot(pen=None, symbol="o", symbolSize=7,
                                     symbolBrush="#4fc3f7", name="laser σx")
        self.c_lwy = self.p_sig.plot(pen=None, symbol="s", symbolSize=7,
                                     symbolBrush="#81c784", name="laser σy")
        self.c_wsx = self.p_sig.plot(pen=None, symbol="t", symbolSize=8,
                                     symbolBrush="#ffb74d", name="wire σx")
        self.p_sig.addLegend(offset=(6, 6), labelTextSize="8pt")
        self.body.addWidget(self.p_sig, 2)

        # ---- scraper jaws (halo scraping + biased current readback)
        from PyQt6.QtWidgets import QDoubleSpinBox, QGridLayout
        scr = QGridLayout()
        scr.addWidget(QLabel("<b>Scraper jaws</b> (pos mm / bias V / µA):"),
                      0, 0, 1, 5)
        self._scr_rows = {}
        names = [e.name for e in self.lat.elements if e.type == "scraper2"]
        for r_, nm in enumerate(names, start=1):
            scr.addWidget(QLabel(nm), r_, 0)
            sp = QDoubleSpinBox(); sp.setRange(0.5, 30.0); sp.setValue(30.0)
            sb = QDoubleSpinBox(); sb.setRange(0.0, 300.0); sb.setValue(150.0)
            lab = QLabel("—")
            btn = QPushButton("Apply")
            btn.clicked.connect(lambda _, n=nm, a=sp, b=sb: (
                self.hub.set_setting("scraper", n, "pos_mm", a.value()),
                self.hub.set_setting("scraper", n, "bias_v", b.value())))
            for c_, w_ in enumerate((sp, sb, lab, btn), start=1):
                scr.addWidget(w_, r_, c_)
            self._scr_rows[nm] = lab
        self.body.addLayout(scr)
        self.hub.scraper.connect(self._on_scraper)

        # ---- Allison scanner
        alli = QHBoxLayout()
        alli.addWidget(QLabel("<b>Allison scanner</b> (MEBT x-x′):"))
        self.btn_alli = QPushButton("Run scan")
        alli.addWidget(self.btn_alli)
        self.lbl_alli = QLabel("—")
        alli.addWidget(self.lbl_alli, 1)
        self.body.addLayout(alli)
        self.img_alli = pg.ImageView()
        self.img_alli.ui.roiBtn.hide(); self.img_alli.ui.menuBtn.hide()
        self.img_alli.setMaximumHeight(240)
        self.body.addWidget(self.img_alli)
        self.btn_alli.clicked.connect(
            lambda: self.hub.r.hset("req:allison", mapping={"steps": 48}))
        self.hub.allison.connect(self._on_allison)

        self.btn_cycle.clicked.connect(self._start_cycle)
        self.btn_cyc_stop.clicked.connect(
            lambda: self.hub.set_setting("profilers", "main", "cycle", 0))
        self._cyc_gate = 0
        self.hub.beamState.connect(self._poll_cycle)
        self.hub.scan.connect(self._on_scan)
        self.hub.deep.connect(self._on_deep)      # phase-space/emit/cloud

    def _on_scraper(self, _pid, data):
        if not self.isVisible():
            return
        for nm, lab in self._scr_rows.items():
            v = data.get(f"{nm}:i_ua")
            if v is not None and len(v):
                ua = float(v[0])
                lab.setText(f"{ua:8.3f} µA")
                lab.setStyleSheet(
                    f"color: {'#ff7043' if ua > 50 else '#2ecc71'};")

    def _on_allison(self, _pid, data):
        if not self.isVisible():
            return
        import numpy as np
        n = int(float(data["n"][0]))
        img = np.asarray(data["img"], dtype=float).reshape(n, n)
        self.img_alli.setImage(img.T, autoLevels=True)
        self.lbl_alli.setText(
            f"ε = {float(data['eps_ummrad'][0]):.3f} mm·mrad rms   "
            f"α = {float(data['alpha'][0]):+.2f}   "
            f"β = {float(data['beta_m'][0]):.2f} m"
            + ("   ✓ complete" if float(data['done'][0]) else "   scanning…"))

    def _start_cycle(self):
        for f, v in (("ws_points", self.sp_wsp.value()),
                     ("ws_ppp", self.sp_wsq.value()),
                     ("lw_points", self.sp_lwp.value()),
                     ("lw_ppp", self.sp_lwq.value()),
                     ("cycle", 1)):
            self.hub.set_setting("profilers", "main", f, v)

    def _poll_cycle(self, _st):
        self._cyc_gate += 1
        if not self.isVisible() or self._cyc_gate % 10:
            return
        st = {k.decode(): v.decode() for k, v in
              self.hub.r.hgetall("state:profilers").items()}
        if st:
            self.lbl_cycle.setText(st.get("status", ""))
        raw = self.hub.r.get("state:profile.summary")
        if not raw:
            return
        import json as _json
        try:
            summ = _json.loads(raw)["stations"]
        except (ValueError, KeyError):
            return
        ws_pos = {e.name: e.s for e in self.lat.instruments("wire_scanner")}
        lx, ly, lxs, wx = [], [], [], []
        for nm, d in summ.items():
            if ":LW" in nm and nm in self.lw_pos:
                lx.append((self.lw_pos[nm], d["sig_x_mm"]))
                ly.append((self.lw_pos[nm], d["sig_y_mm"]))
            elif nm in ws_pos:
                wx.append((ws_pos[nm], d["sig_x_mm"]))
        for curve, pts in ((self.c_lwx, lx), (self.c_lwy, ly),
                           (self.c_wsx, wx)):
            if pts:
                pts.sort()
                curve.setData([p[0] for p in pts], [p[1] for p in pts])

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
                ext = data.get(f"ps:{sec}:{key}:ext")
                if ext is not None:
                    x0, x1, y0, y1 = (float(v) for v in np.ravel(ext))
                    item.setRect(pg.QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
                    self.ps_plots[key].setRange(xRange=(x0, x1),
                                                yRange=(y0, y1), padding=0.02)
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
