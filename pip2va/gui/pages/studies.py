"""Beam Studies: describe a study in plain language, the AI compiles it into
a validated scan plan, the machine executes it, and the AI writes the report."""
from __future__ import annotations

import json
import time
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QProgressBar,
                             QPushButton, QSplitter, QTextEdit, QVBoxLayout,
                             QWidget)

from pip2va.analysis import knowledge, studies, study_presets

from .. import theme
from . import register
from .common import Page

STUDY_DIR = Path.home() / ".pip2va" / "studies"


class PlanWorker(QThread):
    done = pyqtSignal(object, str)     # plan | None, note/error

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            plan, note = studies.plan_from_text(self.text)
            self.done.emit(plan, note)
        except Exception as e:
            self.done.emit(None, str(e))


class ReportWorker(QThread):
    done = pyqtSignal(str, str)

    def __init__(self, plan, result):
        super().__init__()
        self.plan, self.result = plan, result

    def run(self):
        text, engine = studies.llm_report(self.plan, self.result)
        self.done.emit(text, engine)


@register("Studies")
class StudiesPage(Page):
    title = "Beam Studies — AI-planned scans"

    def build(self):
        STUDY_DIR.mkdir(parents=True, exist_ok=True)

        # ---- natural-language request
        from PyQt6.QtWidgets import QComboBox, QTabWidget
        bar = QHBoxLayout()
        self.sel_preset = QComboBox()
        self.sel_preset.addItem("— presets —")
        for nm, pr in study_presets.PRESETS.items():
            self.sel_preset.addItem(nm)
            self.sel_preset.setItemData(self.sel_preset.count() - 1,
                                        pr["teaches"], 3)  # tooltip
        self.btn_preset = QPushButton("Load preset")
        bar.addWidget(self.sel_preset)
        bar.addWidget(self.btn_preset)
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(
            'e.g. "sweep SSR2:CAV17 phase ±15° and amplitude ±5% over two '
            'minutes"  or  "ramp source current from 4 to 6 mA safely"')
        self.btn_plan = QPushButton("Plan with AI")
        bar.addWidget(self.ed, 1)
        bar.addWidget(self.btn_plan)
        self.body.addLayout(bar)
        self.lbl_note = QLabel("")
        self.lbl_note.setStyleSheet("color:#8b96a5;")
        self.lbl_note.setWordWrap(True)
        self.body.addWidget(self.lbl_note)

        split = QSplitter()
        # plan editor
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Plan (editable JSON):"))
        self.txt_plan = QTextEdit()
        ll.addWidget(self.txt_plan, 1)
        row = QHBoxLayout()
        self.btn_queue = QPushButton("Queue")
        self.btn_save = QPushButton("Save…")
        self.btn_load = QPushButton("Load…")
        for b in (self.btn_queue, self.btn_save, self.btn_load):
            row.addWidget(b)
        ll.addLayout(row)
        split.addWidget(left)

        # queue + execution
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.addWidget(QLabel("Study queue (double-click to remove):"))
        self.lst = QListWidget()
        ml.addWidget(self.lst, 1)
        self.chk_auto = QCheckBox("Auto-run queue")
        self.btn_run = QPushButton("RUN next study")
        self.btn_run.setObjectName("danger")
        self.btn_abort = QPushButton("Abort")
        self.prog = QProgressBar()
        self.lbl_run = QLabel("idle")
        ml.addWidget(self.chk_auto)
        ml.addWidget(self.btn_run)
        ml.addWidget(self.btn_abort)
        ml.addWidget(self.prog)
        ml.addWidget(self.lbl_run)
        split.addWidget(mid)

        # report
        right = QWidget()
        rl = QVBoxLayout(right)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Post-study report:"))
        self.btn_ai = QPushButton("AI analysis")
        self.lbl_engine = QLabel("")
        self.lbl_engine.setStyleSheet("color:#8b96a5;")
        hdr.addWidget(self.btn_ai)
        hdr.addWidget(self.lbl_engine)
        hdr.addStretch(1)
        rl.addLayout(hdr)
        self.txt_report = QTextEdit()
        self.txt_report.setReadOnly(True)
        rl.addWidget(self.txt_report, 1)
        split.addWidget(right)
        split.setSizes([380, 260, 480])
        tabs = QTabWidget()
        run_tab = QWidget()
        rt = QVBoxLayout(run_tab)
        rt.setContentsMargins(0, 0, 0, 0)
        rt.addWidget(split)
        tabs.addTab(run_tab, "Plan && Run")

        # ---- Previous studies tab
        hist = QWidget()
        hl = QHBoxLayout(hist)
        hleft = QVBoxLayout()
        hleft.addWidget(QLabel("Completed studies:"))
        self.lst_hist = QListWidget()
        hleft.addWidget(self.lst_hist, 1)
        row_h = QHBoxLayout()
        self.btn_hist_refresh = QPushButton("Refresh")
        self.btn_hist_load = QPushButton("Load plan → editor")
        self.btn_hist_ai = QPushButton("AI re-analysis")
        for b in (self.btn_hist_refresh, self.btn_hist_load,
                  self.btn_hist_ai):
            row_h.addWidget(b)
        hleft.addLayout(row_h)
        hl.addLayout(hleft, 1)
        hr = QVBoxLayout()
        hr.addWidget(QLabel("Report / knowledge:"))
        self.txt_hist = QTextEdit()
        self.txt_hist.setReadOnly(True)
        hr.addWidget(self.txt_hist, 2)
        hr.addWidget(QLabel("Knowledge base (feeds the AI planner "
                            "and trip analysis):"))
        self.txt_kb = QTextEdit()
        self.txt_kb.setReadOnly(True)
        self.txt_kb.setMaximumHeight(150)
        hr.addWidget(self.txt_kb)
        hl.addLayout(hr, 2)
        tabs.addTab(hist, "Previous studies")
        self.body.addWidget(tabs, 1)

        self._queue: list[dict] = []
        self._running: dict | None = None
        self._worker = None
        self._rep_worker = None
        self.btn_plan.clicked.connect(self._plan)
        self.btn_preset.clicked.connect(self._load_preset)
        self.btn_hist_refresh.clicked.connect(self._hist_refresh)
        self.lst_hist.currentTextChanged.connect(self._hist_show)
        self.btn_hist_load.clicked.connect(self._hist_to_editor)
        self.btn_hist_ai.clicked.connect(self._hist_ai)
        self._hist_refresh()
        self.ed.returnPressed.connect(self._plan)
        self.btn_queue.clicked.connect(self._enqueue)
        self.btn_save.clicked.connect(self._save)
        self.btn_load.clicked.connect(self._load)
        self.btn_run.clicked.connect(self._run_next)
        self.btn_abort.clicked.connect(self._abort)
        self.btn_ai.clicked.connect(self._ai_report)
        self.lst.itemDoubleClicked.connect(
            lambda it: (self._queue.pop(self.lst.row(it)),
                        self.lst.takeItem(self.lst.row(it))))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(1000)

    def _load_preset(self):
        nm = self.sel_preset.currentText()
        if nm not in study_presets.PRESETS:
            return
        plan = study_presets.get_plan(nm)
        plan, note = studies.validate_plan(plan)
        self.txt_plan.setPlainText(json.dumps(plan, indent=1))
        self.lbl_note.setText(
            f"preset '{nm}' — teaches: "
            f"{study_presets.PRESETS[nm]['teaches']}  [{note}]")

    # --------------------------------------------------------- history tab

    def _hist_files(self):
        return sorted(STUDY_DIR.glob("result-*.json"), reverse=True)

    def _hist_refresh(self):
        self.lst_hist.clear()
        for f in self._hist_files():
            self.lst_hist.addItem(f.stem.replace("result-", ""))
        kb = knowledge.load(30)
        self.txt_kb.setPlainText("\n".join(
            "- " + k.get("summary", "") for k in reversed(kb)) or
            "(empty — completed studies will appear here)")

    def _hist_sel(self):
        it = self.lst_hist.currentItem()
        if not it:
            return None
        f = STUDY_DIR / f"result-{it.text()}.json"
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            return None

    def _hist_show(self, _txt):
        data = self._hist_sel()
        if data:
            self.txt_hist.setPlainText(
                studies.rule_report(data["plan"], data["result"]))

    def _hist_to_editor(self):
        data = self._hist_sel()
        if data:
            self.txt_plan.setPlainText(json.dumps(data["plan"], indent=1))
            self.lbl_note.setText("plan loaded from history — edit spans/"
                                  "steps for the next-generation study")

    def _hist_ai(self):
        data = self._hist_sel()
        if not data:
            return
        self.txt_hist.setPlainText("AI re-analysis running…")
        self._rep_worker = ReportWorker(data["plan"], data["result"])
        self._rep_worker.done.connect(
            lambda t, e: self.txt_hist.setPlainText(f"[{e}]\n\n{t}"))
        self._rep_worker.start()

    # -------------------------------------------------------------- planning

    def _plan(self):
        text = self.ed.text().strip()
        if not text:
            return
        self.btn_plan.setEnabled(False)
        self.lbl_note.setText("planning with the local LLM…")
        self._worker = PlanWorker(text)
        self._worker.done.connect(self._planned)
        self._worker.start()

    def _planned(self, plan, note):
        self.btn_plan.setEnabled(True)
        if plan is None:
            self.lbl_note.setText(f"✗ {note} — you can still write the "
                                  "plan JSON by hand and Queue it.")
            return
        self.txt_plan.setPlainText(json.dumps(plan, indent=1))
        self.lbl_note.setText(f"✓ {plan.get('rationale', '')}  [{note}]")

    def _current_plan(self):
        try:
            plan, note = studies.validate_plan(
                json.loads(self.txt_plan.toPlainText()))
            self.lbl_note.setText(f"validated: {note}")
            return plan
        except Exception as e:
            self.lbl_note.setText(f"✗ invalid plan: {e}")
            return None

    def _enqueue(self):
        plan = self._current_plan()
        if plan:
            self._queue.append(plan)
            self.lst.addItem(f"{plan['name']}  ({plan['steps']}×"
                             f"{plan['dwell_s']:.1f}s)")

    def _save(self):
        plan = self._current_plan()
        if not plan:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save study", str(STUDY_DIR / f"{plan['name']}.json"),
            "Study (*.json)")
        if path:
            Path(path).write_text(json.dumps(plan, indent=1))

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load study", str(STUDY_DIR), "Study (*.json)")
        if path:
            self.txt_plan.setPlainText(Path(path).read_text())
            self._current_plan()

    # ------------------------------------------------------------- execution

    def _run_next(self):
        if self._running or not self._queue:
            return
        plan = self._queue.pop(0)
        self.lst.takeItem(0)
        self._running = plan
        self.hub.r.hset("state:study", mapping={
            "plan": json.dumps(plan), "run": 1, "status": "starting",
            "step": 0, "total": plan["steps"], "result": ""})
        self.lbl_run.setText(f"running: {plan['name']}")
        self.txt_report.clear()

    def _abort(self):
        self.hub.r.hset("state:study", "run", 0)
        self.hub.rescue()   # restore machine to golden/design
        self.lbl_run.setText("aborted — RESCUE issued")
        self._running = None

    def _poll(self):
        if not self.isVisible() and self._running is None:
            return
        st = {k.decode(): v.decode()
              for k, v in self.hub.r.hgetall("state:study").items()}
        if not st:
            return
        total = int(float(st.get("total", 1) or 1))
        self.prog.setMaximum(total)
        self.prog.setValue(int(float(st.get("step", 0) or 0)))
        if self._running and st.get("run") != "1" and st.get("result"):
            result = json.loads(st["result"])
            plan = self._running
            self._running = None
            self.lbl_run.setText(f"{plan['name']}: {result['status']}")
            self.txt_report.setPlainText(
                studies.rule_report(plan, result))
            self.lbl_engine.setText("engine: rules")
            self._last = (plan, result)
            ts = time.strftime("%Y%m%d-%H%M%S")
            (STUDY_DIR / f"result-{plan['name']}-{ts}.json").write_text(
                json.dumps({"plan": plan, "result": result}, indent=1))
            knowledge.append(knowledge.summarize_result(plan, result))
            self._hist_refresh()
            if self.chk_auto.isChecked() and self._queue:
                self._run_next()

    def _ai_report(self):
        if not getattr(self, "_last", None):
            return
        self.lbl_engine.setText("engine: LLM thinking…")
        self._rep_worker = ReportWorker(*self._last)
        self._rep_worker.done.connect(
            lambda t, e: (self.txt_report.setPlainText(t),
                          self.lbl_engine.setText(f"engine: {e}")))
        self._rep_worker.start()
