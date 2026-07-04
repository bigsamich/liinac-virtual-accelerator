"""Machine snapshots: save / compare / restore (SCORE-style)."""
from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from pip2va.common import snapshots

from .. import theme
from . import register
from .common import Page


@register("Snapshots")
class SnapshotsPage(Page):
    title = "Machine Snapshots — Save / Compare / Restore"

    def build(self):
        bar = QHBoxLayout()
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("snapshot name…")
        self.ed_note = QLineEdit()
        self.ed_note.setPlaceholderText("note (optional)")
        self.btn_save = QPushButton("Save current machine")
        bar.addWidget(self.ed_name, 1)
        bar.addWidget(self.ed_note, 2)
        bar.addWidget(self.btn_save)
        self.body.addLayout(bar)

        mid = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Saved snapshots:"))
        self.lst = QListWidget()
        left.addWidget(self.lst, 1)
        row = QHBoxLayout()
        self.btn_diff = QPushButton("Compare to live")
        self.btn_restore = QPushButton("RESTORE")
        self.btn_restore.setObjectName("danger")
        row.addWidget(self.btn_diff)
        row.addWidget(self.btn_restore)
        left.addLayout(row)
        mid.addLayout(left, 1)

        right = QVBoxLayout()
        self.lbl_diff = QLabel("differences vs live machine:")
        right.addWidget(self.lbl_diff)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Device", "Field", "Live", "Snapshot"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        right.addWidget(self.table, 1)
        mid.addLayout(right, 2)
        self.body.addLayout(mid, 1)

        self.btn_save.clicked.connect(self._save)
        self.btn_diff.clicked.connect(self._diff)
        self.btn_restore.clicked.connect(self._restore)
        self._refresh()

    def _refresh(self):
        self.lst.clear()
        for s in reversed(snapshots.list_snapshots()):
            ts = datetime.datetime.fromtimestamp(s["t"]).strftime("%m-%d %H:%M")
            note = f"  — {s['note']}" if s["note"] else ""
            self.lst.addItem(f"{s['name']}   ({ts}, {s['n']} devices){note}")

    def _selected_name(self) -> str | None:
        it = self.lst.currentItem()
        return it.text().split("   ")[0] if it else None

    def _save(self):
        name = self.ed_name.text().strip().replace("/", "_")
        if not name:
            return
        snapshots.save(self.hub.r, name, self.ed_note.text().strip())
        self.ed_name.clear()
        self._refresh()

    def _diff(self):
        name = self._selected_name()
        if not name:
            return
        d = snapshots.diff(self.hub.r, snapshots.load(name), tol=1e-4)
        self.table.setRowCount(0)
        for e in d[:500]:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(
                e["key"].split(":", 1)[1]))
            self.table.setItem(r, 1, QTableWidgetItem(str(e["field"])))
            for col, v in ((2, e["live"]), (3, e["saved"])):
                it = QTableWidgetItem(
                    f"{v:.4g}" if isinstance(v, float) else str(v))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r, col, it)
        self.lbl_diff.setText(
            f"'{name}' vs live: {len(d)} difference(s)"
            + (" — machine matches snapshot" if not d else ""))
        self.lbl_diff.setStyleSheet(
            f"color:{theme.OK if not d else theme.WARN};")

    def _restore(self):
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(
                self, "Restore snapshot",
                f"Write all setpoints from '{name}' to the machine?"
        ) != QMessageBox.StandardButton.Yes:
            return
        n = snapshots.restore(self.hub.r, snapshots.load(name))
        self.lbl_diff.setText(f"restored {n} setpoints from '{name}' — "
                              "readbacks are slewing")
        self.lbl_diff.setStyleSheet(f"color:{theme.OK};")
