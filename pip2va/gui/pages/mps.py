"""MPS panel: beam permit, trip log, root-cause analysis, fault injector."""
from __future__ import annotations

import datetime

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QFrame, QHBoxLayout, QLabel, QListWidget,
                             QPushButton, QSpinBox, QTabWidget, QTableWidget,
                             QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from pip2va.analysis import llm, root_cause

from .. import theme
from ..widgets import Led
from . import register
from .common import Page

FAULT_UNITS = {"trip": "(magnitude ignored)",
               "detune": "Hz of cavity detuning",
               "drift": "A per minute of supply drift"}


class LlmWorker(QThread):
    done = pyqtSignal(str, str)

    def __init__(self, evidence):
        super().__init__()
        self.evidence = evidence

    def run(self):
        text, engine = llm.analyze(self.evidence)
        self.done.emit(text, engine)


@register("MPS")
class MpsPage(Page):
    title = "Machine Protection System"

    def build(self):
        tabs = QTabWidget()
        tabs.addTab(self._build_status(), "Status & Trip Log")
        tabs.addTab(self._build_analysis(), "Fault Analysis")
        tabs.addTab(self._build_faults(), "Fault Injection (expert)")
        self.body.addWidget(tabs, 1)
        self.tabs = tabs
        self._worker = None
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
        if ev.get("kind") == "trip":
            # instant rule-based diagnosis on every trip
            self._run_rules()

    # -------------------------------------------------------------- analysis

    def _build_analysis(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.btn_rules = QPushButton("Analyze last trip (instant)")
        self.btn_llm = QPushButton("Deep analysis (local LLM)")
        self.lbl_engine = QLabel("")
        self.lbl_engine.setStyleSheet("color:#8b96a5;")
        bar.addWidget(self.btn_rules)
        bar.addWidget(self.btn_llm)
        bar.addWidget(self.lbl_engine)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.txt_analysis = QTextEdit()
        self.txt_analysis.setReadOnly(True)
        self.txt_analysis.setPlaceholderText(
            "When the MPS trips, an instant rule-based diagnosis appears "
            "here automatically. 'Deep analysis' sends the evidence pack to "
            "the local LLM (Ollama) for a physics narrative.")
        lay.addWidget(self.txt_analysis, 1)
        self.btn_rules.clicked.connect(self._run_rules)
        self.btn_llm.clicked.connect(self._run_llm)
        if not llm.available():
            self.btn_llm.setText("Deep analysis (LLM offline)")
        return w

    def _collect(self):
        return root_cause.collect_evidence(self.hub.r, self.lat)

    def _run_rules(self):
        ev = self._collect()
        self.txt_analysis.setPlainText(root_cause.rule_based_summary(ev))
        self.lbl_engine.setText("engine: rules")
        self.tabs.setCurrentIndex(1)

    def _run_llm(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_llm.setEnabled(False)
        self.lbl_engine.setText(f"engine: {llm.MODEL} thinking…")
        self._worker = LlmWorker(self._collect())
        self._worker.done.connect(self._llm_done)
        self._worker.start()

    def _llm_done(self, text: str, engine: str):
        self.txt_analysis.setPlainText(text)
        self.lbl_engine.setText(f"engine: {engine}")
        self.btn_llm.setEnabled(True)

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
        self.lbl_units = QLabel(FAULT_UNITS["trip"])
        self.lbl_units.setStyleSheet("color:#8b96a5;")
        self.f_ttl = QSpinBox()
        self.f_ttl.setRange(0, 3600)
        self.f_ttl.setSuffix(" s (0 = latched)")
        self.btn_apply = QPushButton("Inject fault")
        self.btn_apply.setObjectName("danger")
        self.btn_clear = QPushButton("Clear fault")
        form.addRow("Device class", self.f_cls)
        form.addRow("Device", self.f_dev)
        form.addRow("Fault type", self.f_type)
        form.addRow("Magnitude", self.f_mag)
        form.addRow("", self.lbl_units)
        form.addRow("Auto-clear TTL", self.f_ttl)
        form.addRow(self.btn_apply, self.btn_clear)
        panel.setEnabled(False)
        lay.addWidget(panel)

        self.lbl_fault_status = QLabel(
            "Note: faults act on the live machine — the beam permit must be "
            "ON to see their effect.")
        self.lbl_fault_status.setStyleSheet("color:#8b96a5;")
        lay.addWidget(self.lbl_fault_status)
        lay.addWidget(QLabel("Active injected faults:"))
        self.lst_active = QListWidget()
        self.lst_active.setMaximumHeight(140)
        lay.addWidget(self.lst_active)
        lay.addStretch(1)

        self.chk_expert.toggled.connect(panel.setEnabled)
        self.f_cls.currentTextChanged.connect(self._fill_devices)
        self.f_type.currentTextChanged.connect(
            lambda t: self.lbl_units.setText(FAULT_UNITS.get(t, "")))
        self.btn_apply.clicked.connect(self._apply_fault)
        self.btn_clear.clicked.connect(self._clear_fault)
        self._fill_devices(self.f_cls.currentText())
        self._refresh_active()
        return w

    def _fill_devices(self, cls: str):
        self.f_dev.clear()
        types = ("rfgap", "rfq") if cls == "rf" else \
            ("solenoid", "quad", "corrector")
        self.f_dev.addItems(
            [e.name for e in self.lat.elements if e.type in types])

    def _refresh_active(self):
        self.lst_active.clear()
        faults = self.hub.active_faults()
        self.lst_active.addItems(faults or ["(none)"])

    def _apply_fault(self):
        self.hub.inject_fault(
            self.f_cls.currentText(), self.f_dev.currentText(),
            self.f_type.currentText(), self.f_mag.value(),
            self.f_ttl.value())
        self.lbl_fault_status.setText(
            f"Injected {self.f_type.currentText()} on "
            f"{self.f_dev.currentText()} — watch the RF/Magnets pages and "
            "the loss display.")
        self._refresh_active()

    def _clear_fault(self):
        self.hub.clear_fault(self.f_cls.currentText(),
                             self.f_dev.currentText())
        self.lbl_fault_status.setText(
            f"Cleared fault on {self.f_dev.currentText()}. If the device is "
            "latched TRIPPED, reset it (RF page) then RESET PERMIT.")
        self._refresh_active()
