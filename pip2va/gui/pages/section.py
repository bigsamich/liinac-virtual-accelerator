"""Per-section machine view: local orbit, losses, and device controls."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem)

from .. import theme
from ..plotkit import CrosshairPlot
from .common import Page, make_plot

CONTROLLED = {"rfgap", "rfq", "solenoid", "quad", "corrector"}


class SectionPage(Page):
    """One lattice section: header, local orbit/losses, device table."""

    backRequested = pyqtSignal()

    def __init__(self, hub, lat, section: str):
        self.section = section
        self.title = f"Section — {section}"
        super().__init__(hub, lat)

    def build(self):
        lat, sec_name = self.lat, self.section
        sec = lat.section(sec_name)
        self.els = [e for e in lat.elements if e.section == sec_name]

        top = QHBoxLayout()
        back = QPushButton("← Dashboard")
        back.clicked.connect(self.backRequested.emit)
        top.addWidget(back)
        top.addStretch(1)
        self.body.addLayout(top)

        cav_n = sum(1 for e in self.els if e.type in ("rfgap", "rfq"))
        mag_n = sum(1 for e in self.els if e.type in ("solenoid", "quad"))
        hdr = QLabel(
            f"s = {sec.s_start:.1f} – {sec.s_end:.1f} m   |   "
            f"W: {sec.w_in:g} → {sec.w_out:g} MeV   |   "
            f"f = {sec.freq_mhz or '—'} MHz   |   "
            f"{cav_n} cavities, {mag_n} focusing magnets")
        hdr.setStyleSheet(f"color:{theme.ACCENT};")
        self.body.addWidget(hdr)

        # local orbit + losses side by side (device-name axes)
        row = QHBoxLayout()
        all_bpms = lat.instruments("bpm")
        self.bpm_idx = [i for i, e in enumerate(all_bpms)
                        if e.section == sec_name]
        bpm_names = [all_bpms[i].name for i in self.bpm_idx]
        self.bpm_s = np.arange(len(self.bpm_idx), dtype=float)
        self.p_orbit = CrosshairPlot("orbit [mm]",
                                     device_names=bpm_names or ["-"])
        self.c_x = self.p_orbit.plot(pen=pg.mkPen(theme.ACCENT, width=1.5),
                                     symbol="o", symbolSize=5,
                                     symbolBrush=theme.ACCENT, name="x")
        self.c_y = self.p_orbit.plot(pen=pg.mkPen("#ffb74d", width=1.5),
                                     symbol="s", symbolSize=5,
                                     symbolBrush="#ffb74d", name="y")
        self.p_orbit.addLegend(offset=(6, 6))
        row.addWidget(self.p_orbit, 1)

        all_blms = lat.instruments("blm")
        self.blm_idx = [i for i, e in enumerate(all_blms)
                        if e.section == sec_name]
        blm_names = [all_blms[i].name for i in self.blm_idx]
        self.p_loss = CrosshairPlot("loss [W/m]",
                                    device_names=blm_names or ["-"])
        self.loss_bars = pg.BarGraphItem(
            x=np.arange(max(len(self.blm_idx), 1), dtype=float),
            height=np.zeros(max(len(self.blm_idx), 1)), width=0.7,
            brush=theme.WARN)
        self.p_loss.addItem(self.loss_bars)
        row.addWidget(self.p_loss, 1)
        self.body.addLayout(row, 2)

        # device table (RF + magnets, settable)
        self.rows = [e for e in self.els if e.type in CONTROLLED]
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Device", "Type", "Setpoint", "Setpoint 2 / phase", "Readback",
             "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self._rb: dict[int, QTableWidgetItem] = {}
        self._st: dict[int, QTableWidgetItem] = {}
        for i, el in enumerate(self.rows):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(el.name))
            self.table.setItem(r, 1, QTableWidgetItem(el.type))
            if el.type in ("rfgap", "rfq"):
                st = self.hub.get_settings("rf", el.name)
                p = el.params
                qlim = p.get("quench_mv",
                             1.3 * p.get("v_mv", p.get("v_design", 1.0)))
                amp = self._spin(0.0, qlim * 1.2, float(st.get(
                    "amp", p.get("v_mv", p.get("v_design", 1.0)))), 3)
                amp.valueChanged.connect(
                    lambda v, el=el: self.hub.set_setting("rf", el.name, "amp", v))
                self.table.setCellWidget(r, 2, amp)
                ph = self._spin(-180, 180, float(st.get(
                    "phase", p.get("phi_deg", 0.0))), 2)
                ph.valueChanged.connect(
                    lambda v, el=el: self.hub.set_setting("rf", el.name,
                                                          "phase", v))
                self.table.setCellWidget(r, 3, ph)
            elif el.type == "corrector":
                st = self.hub.get_settings("magnet", el.name)
                lim = el.params.get("max_amp", 10.0)
                for col, fld in ((2, "current_x"), (3, "current_y")):
                    sp = self._spin(-lim, lim, float(st.get(fld, 0.0)), 3)
                    sp.valueChanged.connect(
                        lambda v, el=el, fld=fld: self.hub.set_setting(
                            "magnet", el.name, fld, v))
                    self.table.setCellWidget(r, col, sp)
            else:  # solenoid / quad
                st = self.hub.get_settings("magnet", el.name)
                lim = el.params.get("max_current", 2000.0)
                sp = self._spin(-lim, lim, float(st.get(
                    "current", el.params["design_current"])), 3)
                sp.valueChanged.connect(
                    lambda v, el=el: self.hub.set_setting(
                        "magnet", el.name, "current", v))
                self.table.setCellWidget(r, 2, sp)
                self.table.setItem(r, 3, QTableWidgetItem("—"))
            rb = QTableWidgetItem("—")
            rb.setFlags(Qt.ItemFlag.ItemIsEnabled)
            stat = QTableWidgetItem("—")
            stat.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 4, rb)
            self.table.setItem(r, 5, stat)
            self._rb[i] = rb
            self._st[i] = stat
        self.body.addWidget(self.table, 3)

        from ..linac3d import Linac3D
        self.view3d = Linac3D(self.lat, section=self.section, values=True)
        self.body.addWidget(self.view3d, 2)
        self.hub.toroids.connect(self._on_tor3d)

        self._rf_pos = None
        self._mag_pos = None
        self.hub.orbit.connect(self._on_orbit)
        self.hub.losses.connect(self._on_losses)
        self.hub.rf.connect(self._on_rf)
        self.hub.magnets.connect(self._on_magnets)

    @staticmethod
    def _spin(lo, hi, val, dec):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(dec)
        sp.setValue(val)
        return sp

    # ---------------------------------------------------------- live data

    def _on_orbit(self, _pid, data):
        if not self.isVisible() or not len(self.bpm_idx):
            return
        x = data["x"][self.bpm_idx] * 1e3
        y = data["y"][self.bpm_idx] * 1e3
        self.c_x.setData(self.bpm_s, x)
        self.c_y.setData(self.bpm_s, y)
        self.p_orbit.update_y(x, y)
        self.view3d.update_orbit(data["x"] * 1e3, data["y"] * 1e3)

    def _on_losses(self, _pid, data):
        if not self.isVisible() or not len(self.blm_idx):
            return
        self.loss_bars.setOpts(height=data["wpm"][self.blm_idx])
        self.view3d.update_losses(data["wpm"])

    def _on_rf(self, _pid, data):
        if not self.isVisible():
            return
        if self._rf_pos is None:
            idx = self.hub.get_index("rf")
            self._rf_pos = {n: j for j, n in enumerate(idx)} if idx else {}
        for i, el in enumerate(self.rows):
            if el.type not in ("rfgap", "rfq"):
                continue
            j = self._rf_pos.get(el.name)
            if j is None or j >= len(data["amp"]):
                continue
            self._rb[i].setText(f'{data["amp"][j]:.3f} MV / '
                                f'{data["phase"][j]:.1f}°')
            self._set_status(i, data["status"][j] > 0.5)
            self.view3d.update_values({el.name:
                f'{el.name.split(":")[1]} {data["amp"][j]:.2f}MV '
                f'{data["phase"][j]:+.0f}°'})

    def _on_magnets(self, _pid, data):
        if not self.isVisible():
            return
        if self._mag_pos is None:
            idx = self.hub.get_index("magnet")
            self._mag_pos = {n: j for j, n in enumerate(idx)} if idx else {}
        for i, el in enumerate(self.rows):
            if el.type == "corrector":
                jx = self._mag_pos.get(f"{el.name}:current_x")
                jy = self._mag_pos.get(f"{el.name}:current_y")
                if jx is not None and jy is not None \
                        and max(jx, jy) < len(data["values"]):
                    self._rb[i].setText(f'{data["values"][jx]:+.2f} / '
                                        f'{data["values"][jy]:+.2f} A')
                    self._set_status(i, data["status"][jx] > 0.5)
                    self.view3d.update_values({el.name:
                        f'{el.name.split(":")[1]} '
                        f'{data["values"][jx]:+.2f}/'
                        f'{data["values"][jy]:+.2f}A'})
            elif el.type in ("solenoid", "quad"):
                j = self._mag_pos.get(f"{el.name}:current")
                if j is not None and j < len(data["values"]):
                    self._rb[i].setText(f'{data["values"][j]:.2f} A')
                    self._set_status(i, data["status"][j] > 0.5)
                    self.view3d.update_values({el.name:
                        f'{el.name.split(":")[1]} '
                        f'{data["values"][j]:.1f}A'})

    def _on_tor3d(self, _pid, data):
        if not self.isVisible():
            return
        tors = self.lat.instruments("toroid")
        vals = {t.name: f'{t.name.split(":")[1]} {data["i_ma"][j]:.2f}mA'
                for j, t in enumerate(tors)
                if t.section == self.section and j < len(data["i_ma"])}
        self.view3d.update_values(vals)

    def _set_status(self, i, tripped: bool):
        from PyQt6.QtGui import QBrush, QColor
        self._st[i].setText("TRIPPED" if tripped else "ok")
        self._st[i].setForeground(
            QBrush(QColor(theme.ALARM if tripped else theme.OK)))
