"""What-If — fork deterministic branches from a snapshot and compare.

Runs the sim.branch engine with Common Random Numbers: every branch starts from
the same snapshot with the same noise, so metric differences are pure signal
from the knob delta (not RNG variance). Also drives the injection auto-tuner.
All heavy work runs on a QThread so the control room never freezes.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem)

from .. import theme
from . import register
from .common import Page, make_plot

# metrics the branch engine reports -> (label, higher_is_better)
_METRICS = {
    "inj_score_mean": ("Injection score", True),
    "worst_blm_mean": ("Worst BLM [W/m]", False),
    "orbit_rms_mm": ("Orbit rms [mm]", False),
    "transmission_min": ("Transmission (min)", True),
}
_WARMUP = 15
_NPULSE = 6


class _Worker(QThread):
    """Builds a snapshot and runs a job (fork or auto-tune) off the UI thread."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job, *args):
        super().__init__()
        self.job, self.args = job, args

    def run(self):
        try:
            from pip2va.sim import snapshot
            from pip2va.sim.driver import SimDriver
            d = SimDriver()
            d.run(_WARMUP, {})                      # settle from design
            base = snapshot.capture(d)
            self.done.emit(self.job(base, *self.args))
        except Exception as e:                      # surface, don't crash GUI
            self.failed.emit(f"{type(e).__name__}: {e}")


@register("What-If")
class WhatIfPage(Page):
    title = "What-If — deterministic branch explorer"

    def build(self):
        self._worker = None
        # candidate knobs: correctors from the lattice + injection painting knobs
        corr = [f"{e.name}:current_x" for e in self.lat.elements
                if e.type == "corrector"][:40]
        self._knobs = ["inj:bump0_mm", "inj:decay_turns"] + corr

        row = QHBoxLayout()
        row.addWidget(QLabel("Knob"))
        self.cmb_knob = QComboBox()
        self.cmb_knob.addItems(self._knobs)
        self.cmb_knob.currentTextChanged.connect(self._preset_values)
        row.addWidget(self.cmb_knob, 2)
        row.addWidget(QLabel("Values"))
        self.ed_vals = QLineEdit("4, 8, 12, 16, 20")
        row.addWidget(self.ed_vals, 2)
        row.addWidget(QLabel("Metric"))
        self.cmb_metric = QComboBox()
        for k, (lbl, _) in _METRICS.items():
            self.cmb_metric.addItem(lbl, k)
        self.cmb_metric.currentIndexChanged.connect(self._redraw)
        row.addWidget(self.cmb_metric, 1)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_run = QPushButton("Run what-if")
        self.btn_run.clicked.connect(self._run_fork)
        self.btn_tune = QPushButton("Auto-tune injection")
        self.btn_tune.setObjectName("danger")
        self.btn_tune.clicked.connect(self._run_tune)
        self.lbl_status = QLabel("fork branches from a snapshot of the design "
                                 "machine — shared noise, so differences are "
                                 "pure signal")
        self.lbl_status.setStyleSheet("color:#8b96a5;")
        row2.addWidget(self.btn_run)
        row2.addWidget(self.btn_tune)
        row2.addWidget(self.lbl_status, 1)
        self.body.addLayout(row2)

        self.plot = make_plot("metric", xlabel="knob value", height=240)
        self.plot.setTitle("branch comparison")
        self.body.addWidget(self.plot)

        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(
            ["value", "inj score", "worst BLM", "orbit rms", "T min"])
        self.tbl.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.body.addWidget(self.tbl, 1)
        self._results = []          # (value, metrics)

    # ---------------------------------------------------------------- helpers
    def _preset_values(self, knob: str):
        self.ed_vals.setText(
            "4, 8, 12, 16, 20" if knob == "inj:bump0_mm" else
            "10, 40, 100, 180, 260" if knob == "inj:decay_turns" else
            "-0.8, -0.4, 0, 0.4, 0.8")

    def _parse_values(self):
        out = []
        for tok in self.ed_vals.text().split(","):
            tok = tok.strip()
            if tok:
                try:
                    out.append(float(tok))
                except ValueError:
                    pass
        return out

    def _busy(self, on: bool, msg: str = ""):
        self.btn_run.setEnabled(not on)
        self.btn_tune.setEnabled(not on)
        if msg:
            self.lbl_status.setText(msg)

    # ---------------------------------------------------------------- fork
    def _run_fork(self):
        if self._worker is not None:
            return
        knob = self.cmb_knob.currentText()
        vals = self._parse_values()
        if not vals:
            self.lbl_status.setText("no valid values")
            return
        self._busy(True, f"running {len(vals)} branches…")

        def job(base, knob, vals):
            from pip2va.sim import branch
            deltas = [{knob: v} for v in vals]
            res = branch.fork(base, deltas, _NPULSE,
                              workers=min(4, len(vals)))
            return ("fork", vals, [r.metrics for r in res])

        self._start(job, knob, vals)

    # ---------------------------------------------------------------- autotune
    def _run_tune(self):
        if self._worker is not None:
            return
        self._busy(True, "auto-tuning injection (CRN)…")

        def job(base):
            from pip2va.analysis import optimizer
            r = optimizer.autotune_injection(base, n_pulses=_NPULSE, iters=25)
            return ("tune", r)

        self._start(job)

    def _start(self, job, *args):
        self._worker = _Worker(job, *args)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(self._clear_worker)
        self._worker.start()

    def _clear_worker(self):
        self._worker = None

    def _on_fail(self, msg: str):
        self._busy(False, f"error: {msg}")

    def _on_done(self, payload):
        kind = payload[0]
        if kind == "fork":
            _, vals, metrics = payload
            self._results = list(zip(vals, metrics))
            self._redraw()
            self._busy(False, f"{len(vals)} branches done — shared noise (CRN)")
        else:
            r = payload[1]
            self.ed_vals.setText(", ".join(
                f"{k}={v:g}" for k, v in r.best.items()))
            self._busy(False, f"injection auto-tune: {r.baseline:.1f} → "
                              f"{r.score:.1f}  ({r.n_evals} evals, "
                              f"best {r.best})")

    def _redraw(self):
        self.plot.clear()
        self.tbl.setRowCount(len(self._results))
        if not self._results:
            return
        key = self.cmb_metric.currentData()
        xs = np.array([v for v, _ in self._results], dtype=float)
        ys = np.array([m.get(key, 0.0) for _, m in self._results], dtype=float)
        w = (xs.max() - xs.min()) / max(len(xs), 2) * 0.6 or 0.4
        self.plot.addItem(pg.BarGraphItem(x=xs, height=ys, width=w,
                                          brush=theme.ACCENT))
        self.plot.setLabel("left", _METRICS[key][0])
        # best branch marker
        best_i = int(np.argmax(ys) if _METRICS[key][1] else np.argmin(ys))
        self.plot.addLine(x=xs[best_i], pen=pg.mkPen(theme.OK, width=2,
                          style=pg.QtCore.Qt.PenStyle.DashLine))
        for i, (v, m) in enumerate(self._results):
            cells = [f"{v:g}", f"{m.get('inj_score_mean', 0):.1f}",
                     f"{m.get('worst_blm_mean', 0):.2f}",
                     f"{m.get('orbit_rms_mm', 0):.3f}",
                     f"{m.get('transmission_min', 0):.4f}"]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if i == best_i:
                    it.setForeground(pg.mkColor(theme.OK))
                self.tbl.setItem(i, c, it)
