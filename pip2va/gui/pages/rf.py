"""RF tuner & viewer: per-cavity table with a detail pane."""
from __future__ import annotations

import collections
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem)


class PhaseScanWorker(QThread):
    """Classic commissioning phase scan: sweep cavity phase, record the
    downstream TOF energy, fit the cosine, park at crest + design offset."""

    point = pyqtSignal(float, float)          # phi, W_tof
    done = pyqtSignal(str, float)             # message, new phase

    def __init__(self, hub, cav_name, phi_design, span=180.0, steps=25,
                 settle_s=0.8):
        super().__init__()
        self.hub, self.cav, self.phi_d = hub, cav_name, phi_design
        self.span, self.steps, self.settle = span, steps, settle_s
        self._stop = False

    def stop(self):
        self._stop = True

    def _w_tof(self):
        h = self.hub.history("bpm.orbit", 6)
        ws = [d["w_tof"][-1] for _, d in h if len(d.get("w_tof", []))]
        return float(np.mean(ws)) if ws else 0.0

    def run(self):
        phis = np.linspace(self.phi_d - self.span / 2,
                           self.phi_d + self.span / 2, self.steps)
        ws = []
        for ph in phis:
            if self._stop:
                break
            self.hub.set_setting("rf", self.cav, "phase", float(ph))
            time.sleep(self.settle)
            w = self._w_tof()
            ws.append(w)
            self.point.emit(float(ph), w)
        if self._stop or len(ws) < 5:
            self.hub.set_setting("rf", self.cav, "phase", self.phi_d)
            self.done.emit("scan aborted — phase restored", self.phi_d)
            return
        # cosine fit via FFT-free least squares on cos/sin basis
        ph_r = np.radians(np.array(phis[:len(ws)]))
        A = np.column_stack([np.cos(ph_r), np.sin(ph_r), np.ones_like(ph_r)])
        c, *_ = np.linalg.lstsq(A, np.array(ws), rcond=None)
        crest = np.degrees(np.arctan2(c[1], c[0]))
        new_phase = (crest + self.phi_d + 180.0) % 360.0 - 180.0
        self.hub.set_setting("rf", self.cav, "phase", float(new_phase))
        self.done.emit(
            f"crest at {crest:+.1f} deg -> set {new_phase:+.1f} deg "
            f"(design offset {self.phi_d:+.1f})", new_phase)

from .. import theme
from . import register
from .common import Page, make_plot


@register("RF")
class RfPage(Page):
    title = "RF Systems"

    def build(self):
        self.cavs = [e for e in self.lat.elements
                     if e.type in ("rfgap", "rfq")]
        bar = QHBoxLayout()
        self.sec = QComboBox()
        self.sec.addItem("ALL")
        for s in self.lat.sections:
            if any(c.section == s.name for c in self.cavs):
                self.sec.addItem(s.name)
        bar.addWidget(QLabel("Section:"))
        bar.addWidget(self.sec)
        bar.addStretch(1)
        self.body.addLayout(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Cavity", "Amp set [MV]", "Phase set [deg]", "Amp rb", "Phase rb",
             "Detune [Hz]", "Fwd [norm]", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.body.addWidget(self.table, 2)

        # detail pane
        det_bar = QHBoxLayout()
        self.lbl_sel = QLabel("select a cavity…")
        self.btn_reset = QPushButton("Reset trip")
        self.btn_scan = QPushButton("Phase scan (tune-up)")
        self.lbl_scan = QLabel("")
        self.lbl_scan.setStyleSheet("color:#8b96a5;")
        det_bar.addWidget(self.lbl_sel)
        det_bar.addWidget(self.lbl_scan, 1)
        det_bar.addWidget(self.btn_scan)
        det_bar.addWidget(self.btn_reset)
        self.body.addLayout(det_bar)
        self.p_det = make_plot("detuning [Hz]", xlabel="pulse")
        self.c_det = self.p_det.plot(pen=pg.mkPen(theme.ACCENT, width=1.5))
        self.body.addWidget(self.p_det, 1)

        self._index: list[str] | None = None
        self._hist: dict[str, collections.deque] = {}
        self._visible: list[int] = []
        self._items: dict[int, dict] = {}
        self._sel: str | None = None

        self._scan_worker = None
        self._scan_curve = None
        self.sec.currentTextChanged.connect(self._rebuild)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.btn_reset.clicked.connect(self._reset_sel)
        self.btn_scan.clicked.connect(self._phase_scan)
        self.hub.rf.connect(self._on_rf)
        self._rebuild()

    def _rebuild(self, *_):
        sec = self.sec.currentText()
        self.table.setRowCount(0)
        self._visible = []
        self._items.clear()
        for i, el in enumerate(self.cavs):
            if sec != "ALL" and el.section != sec:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(el.name))
            st = self.hub.get_settings("rf", el.name)
            p = el.params
            amp = QDoubleSpinBox()
            qlim = p.get("quench_mv", 1.3 * p.get("v_mv", p.get("v_design", 1.0)))
            amp.setRange(0.0, qlim * 1.2)
            amp.setToolTip(f"quench limit {qlim:g} MV")
            amp.setDecimals(3)
            amp.setSingleStep(0.05)
            amp.setValue(float(st.get("amp", p.get("v_mv", p.get("v_design", 1.0)))))
            amp.valueChanged.connect(
                lambda v, el=el: self.hub.set_setting("rf", el.name, "amp", v))
            self.table.setCellWidget(r, 1, amp)
            ph = QDoubleSpinBox()
            ph.setRange(-180.0, 180.0)
            ph.setDecimals(2)
            ph.setValue(float(st.get("phase", p.get("phi_deg", 0.0))))
            ph.valueChanged.connect(
                lambda v, el=el: self.hub.set_setting("rf", el.name, "phase", v))
            self.table.setCellWidget(r, 2, ph)
            cells = {}
            for col, key in ((3, "amp"), (4, "phase"), (5, "det"),
                             (6, "fwd"), (7, "status")):
                it = QTableWidgetItem("—")
                it.setFlags(Qt.ItemFlag.ItemIsEnabled |
                            Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, col, it)
                cells[key] = it
            self._items[i] = cells
            self._visible.append(i)

    def _on_select(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._visible):
            self._sel = self.cavs[self._visible[row]].name
            self.lbl_sel.setText(f"detail: {self._sel}")

    def _reset_sel(self):
        if self._sel:
            self.hub.set_setting("rf", self._sel, "reset", 1)

    def _phase_scan(self):
        if not self._sel:
            self.lbl_scan.setText("select a cavity first")
            return
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.stop()
            return
        el = next(c for c in self.cavs if c.name == self._sel)
        phi_d = el.params.get("phi_deg", 0.0)
        self.p_det.clear()
        import pyqtgraph as _pg
        self._scan_curve = self.p_det.plot(
            pen=None, symbol="o", symbolSize=6, symbolBrush="#4db6ac",
            name=f"{self._sel} W_tof vs phase")
        self._scan_pts = ([], [])
        self.p_det.pw.setLabel("left", "W_tof [MeV]")
        self.p_det.pw.setLabel("bottom", "cavity phase [deg]")
        self.btn_scan.setText("STOP scan")
        self.lbl_scan.setText("scanning…")
        self._scan_worker = PhaseScanWorker(self.hub, self._sel, phi_d)
        self._scan_worker.point.connect(self._scan_point)
        self._scan_worker.done.connect(self._scan_done)
        self._scan_worker.start()

    def _scan_point(self, ph, w):
        self._scan_pts[0].append(ph)
        self._scan_pts[1].append(w)
        self._scan_curve.setData(*self._scan_pts)
        self.p_det.update_y(np.array(self._scan_pts[1]))

    def _scan_done(self, msg, _phase):
        self.lbl_scan.setText(msg)
        self.btn_scan.setText("Phase scan (tune-up)")

    def _on_rf(self, _pid, data):
        if self._index is None:
            idx = self.hub.get_index("rf")
            self._index = idx or None
        if not self._index:
            return
        pos = {n: j for j, n in enumerate(self._index)}
        for i in self._visible:
            el = self.cavs[i]
            j = pos.get(el.name)
            if j is None or j >= len(data["amp"]):
                continue
            c = self._items[i]
            c["amp"].setText(f'{data["amp"][j]:.3f}')
            c["phase"].setText(f'{data["phase"][j]:.2f}')
            c["det"].setText(f'{data["detuning_hz"][j]:+.1f}')
            c["fwd"].setText(f'{data["forward_pw"][j]:.2f}')
            tripped = data["status"][j] > 0.5
            c["status"].setText("TRIPPED" if tripped else "ok")
            from PyQt6.QtGui import QBrush, QColor
            c["status"].setForeground(
                QBrush(QColor(theme.ALARM if tripped else theme.OK)))
        # detail history
        for n, j in pos.items():
            if j < len(data["detuning_hz"]):
                self._hist.setdefault(
                    n, collections.deque(maxlen=400)).append(
                        float(data["detuning_hz"][j]))
        if self._sel and self._sel in self._hist:
            h = self._hist[self._sel]
            self.c_det.setData(np.arange(len(h)), np.fromiter(h, float))
