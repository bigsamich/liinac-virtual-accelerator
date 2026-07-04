"""MPS panel: beam permit, trip log, reset — and the expert fault injector."""
from __future__ import annotations

import datetime

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QFrame, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QTabWidget, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from .. import theme
from ..widgets import Led
from . import register
from .common import Page


@register("MPS")
class MpsPage(Page):
    title = "Machine Protection System"

    def build(self):
        tabs = QTabWidget()
        tabs.addTab(self._build_status(), "Status & Trip Log")
        tabs.addTab(self._build_faults(), "Fault Injection (expert)")
        self.body.addWidget(tabs, 1)
        self.hub.mpsEvent.connect(self._on_event)
        self.hub.beamState.connect(self._on_state)
        self._load_history()

    # ---------------------------------------------------------------- status

    def _build_status(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.led = Led(theme.WARN, size=22)
        self.lbl_permit = QLabel("permit: —")
        self.lbl_permit.setStyleSheet("font-size:16px; font-weight:bold;")
        self.btn_reset = QPushButton("RESET beam permit")
        self.btn_relearn = QPushButton("Re-learn BLM baseline")
        bar.addWidget(self.led)
        bar.addWidget(self.lbl_permit)
        bar.addStretch(1)
        bar.addWidget(self.btn_relearn)
        bar.addWidget(self.btn_reset)
        lay.addLayout(bar)

        self.log = QTableWidget(0, 3)
        self.log.setHorizontalHeaderLabels(["Time", "Kind", "Detail"])
        self.log.horizontalHeader().setStretchLastSection(True)
        self.log.verticalHeader().setVisible(False)
        lay.addWidget(self.log, 1)

        self.btn_reset.clicked.connect(self.hub.mps_reset)
        self.btn_relearn.clicked.connect(
            lambda: self.hub.set_setting("mps", "main", "relearn", 1))
        return w

    def _load_history(self):
        for ev in reversed(self.hub.event_history(200)):
            self._append_event(ev)

    def _append_event(self, ev: dict):
        r = 0
        self.log.insertRow(r)
        try:
            ts = datetime.datetime.fromtimestamp(float(ev.get("t", 0)))
            tstr = ts.strftime("%H:%M:%S")
        except (ValueError, OSError):
            tstr = "—"
        kind = ev.get("kind", "?")
        self.log.setItem(r, 0, QTableWidgetItem(tstr))
        it = QTableWidgetItem(kind)
        if kind == "trip":
            from PyQt6.QtGui import QBrush, QColor
            it.setForeground(QBrush(QColor(theme.ALARM)))
        self.log.setItem(r, 1, it)
        self.log.setItem(r, 2, QTableWidgetItem(ev.get("detail", "")))
        if self.log.rowCount() > 300:
            self.log.removeRow(300)

    def _on_event(self, ev: dict):
        self._append_event(ev)

    def _on_state(self, st: dict):
        if not st:
            return
        ok = bool(st.get("permit"))
        self.led.set_color(theme.OK if ok else theme.ALARM)
        self.lbl_permit.setText(
            "permit: BEAM ENABLED" if ok else "permit: BEAM INHIBITED")
        self.lbl_permit.setStyleSheet(
            f"font-size:16px; font-weight:bold; "
            f"color:{theme.OK if ok else theme.ALARM};")

    # ---------------------------------------------------------------- faults

    def _build_faults(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.chk_expert = QCheckBox(
            "I am running a training scenario — enable fault injection")
        lay.addWidget(self.chk_expert)

        panel = QFrame()
        panel.setObjectName("panel")
        form = QFormLayout(panel)
        self.f_cls = QComboBox()
        self.f_cls.addItems(["rf", "magnet"])
        self.f_dev = QComboBox()
        self.f_type = QComboBox()
        self.f_type.addItems(["trip", "detune", "drift"])
        self.f_mag = QDoubleSpinBox()
        self.f_mag.setRange(-1000, 1000)
        self.f_mag.setValue(50.0)
        self.f_ttl = QSpinBox()
        self.f_ttl.setRange(0, 3600)
        self.f_ttl.setSuffix(" s (0 = latched)")
        self.btn_apply = QPushButton("Inject fault")
        self.btn_apply.setObjectName("danger")
        self.btn_clear = QPushButton("Clear fault")
        form.addRow("Device class", self.f_cls)
        form.addRow("Device", self.f_dev)
        form.addRow("Fault type", self.f_type)
        form.addRow("Magnitude (Hz / A·s⁻¹)", self.f_mag)
        form.addRow("Auto-clear TTL", self.f_ttl)
        form.addRow(self.btn_apply, self.btn_clear)
        panel.setEnabled(False)
        lay.addWidget(panel)
        lay.addStretch(1)

        self.chk_expert.toggled.connect(panel.setEnabled)
        self.f_cls.currentTextChanged.connect(self._fill_devices)
        self.btn_apply.clicked.connect(self._apply_fault)
        self.btn_clear.clicked.connect(self._clear_fault)
        self._fill_devices(self.f_cls.currentText())
        return w

    def _fill_devices(self, cls: str):
        self.f_dev.clear()
        types = ("rfgap", "rfq") if cls == "rf" else \
            ("solenoid", "quad", "corrector")
        self.f_dev.addItems(
            [e.name for e in self.lat.elements if e.type in types])

    def _apply_fault(self):
        self.hub.inject_fault(
            self.f_cls.currentText(), self.f_dev.currentText(),
            self.f_type.currentText(), self.f_mag.value(),
            self.f_ttl.value())

    def _clear_fault(self):
        self.hub.clear_fault(self.f_cls.currentText(),
                             self.f_dev.currentText())
