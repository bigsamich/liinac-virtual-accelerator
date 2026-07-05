"""Ask-the-machine panel: LLM Q&A grounded in the live snapshot and the
beam-study knowledge base. Docked under the page stack so it is available
from every page."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLineEdit, QPushButton, QTextEdit,
                             QVBoxLayout, QWidget)


class AskWorker(QThread):
    done = pyqtSignal(str, str)

    def __init__(self, r, question):
        super().__init__()
        self.r, self.q = r, question

    def run(self):
        try:
            from pip2va.analysis import assistant
            text, engine = assistant.ask(self.r, self.q)
            self.done.emit(text, engine)
        except Exception as e:
            self.done.emit(f"assistant error: {e}", "error")


class AskPanel(QWidget):
    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self._worker = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        row = QHBoxLayout()
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(
            "Ask the machine… (status? what happens if I raise the source "
            "to 6 mA? can I run unchopped? why is BTL:BLM1 high?)")
        self.btn = QPushButton("Ask")
        self.btn_hide = QPushButton("×")
        self.btn_hide.setFixedWidth(24)
        self.btn_hide.setToolTip("hide the answer")
        row.addWidget(self.ed, 1)
        row.addWidget(self.btn)
        row.addWidget(self.btn_hide)
        lay.addLayout(row)
        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setMaximumHeight(140)
        self.txt.hide()
        lay.addWidget(self.txt)
        self.btn.clicked.connect(self._ask)
        self.ed.returnPressed.connect(self._ask)
        self.btn_hide.clicked.connect(self.txt.hide)

    def _ask(self):
        q = self.ed.text().strip()
        if not q or (self._worker and self._worker.isRunning()):
            return
        self.txt.show()
        self.txt.setPlainText("thinking…")
        self.btn.setEnabled(False)
        self._worker = AskWorker(self.hub.r, q)
        self._worker.done.connect(self._answered)
        self._worker.start()

    def _answered(self, text, engine):
        self.btn.setEnabled(True)
        self.txt.setPlainText(f"[{engine}]\n{text}")
