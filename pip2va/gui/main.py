"""PIP-II Virtual Accelerator control-room GUI (PyQt6 + pyqtgraph)."""
from __future__ import annotations

import argparse
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget,
                             QMainWindow, QStackedWidget, QStatusBar, QWidget)

from pip2va.common.config import Settings
from pip2va.common.lattice import load_lattice

from . import theme
from .datahub import DataHub
from .widgets import Led


class MainWindow(QMainWindow):
    def __init__(self, hub: DataHub):
        super().__init__()
        self.hub = hub
        self.lat = load_lattice()
        self.setWindowTitle("PIP-II Virtual Accelerator")
        self.resize(1480, 920)

        from .pages import load_all
        pages = load_all()

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setFixedWidth(190)
        self.stack = QStackedWidget()
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._page_classes = list(pages.items())
        self._built: dict[int, QWidget] = {}
        for label, _ in self._page_classes:
            self.nav.addItem(label)
        if not self._page_classes:
            self.nav.addItem("Welcome")
            self.stack.addWidget(QLabel("No pages registered"))
        self.nav.currentRowChanged.connect(self._show_page)

        # status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.led_conn = Led(theme.WARN)
        self.led_permit = Led(theme.WARN)
        self.lbl_pulse = QLabel("pulse —")
        self.lbl_w = QLabel("W —")
        self.lbl_t = QLabel("T —")
        sb.addWidget(QLabel("  link"))
        sb.addWidget(self.led_conn)
        sb.addWidget(QLabel("  beam permit"))
        sb.addWidget(self.led_permit)
        sb.addPermanentWidget(self.lbl_pulse)
        sb.addPermanentWidget(self.lbl_w)
        sb.addPermanentWidget(self.lbl_t)

        hub.connected.connect(
            lambda ok: self.led_conn.set_color(theme.OK if ok else theme.ALARM))
        hub.beamState.connect(self._on_state)

        if self._page_classes:
            self.nav.setCurrentRow(0)

    def _show_page(self, row: int):
        if row < 0 or not self._page_classes:
            return
        if row not in self._built:
            label, cls = self._page_classes[row]
            w = cls(self.hub, self.lat)
            self._built[row] = w
            self.stack.addWidget(w)
        self.stack.setCurrentWidget(self._built[row])

    def goto(self, label: str):
        for i, (lbl, _) in enumerate(self._page_classes):
            if lbl == label:
                self.nav.setCurrentRow(i)
                return

    def _on_state(self, st: dict):
        if not st:
            return
        self.lbl_pulse.setText(f"pulse {int(st.get('pulse_id', 0))}")
        self.lbl_w.setText(f"W {st.get('w_out', 0):.1f} MeV")
        self.lbl_t.setText(f"T {100 * st.get('transmission', 0):.1f} %")
        self.led_permit.set_color(
            theme.OK if st.get("permit") else theme.ALARM)

    def closeEvent(self, ev):
        self.hub.stop()
        super().closeEvent(ev)


def main():
    ap = argparse.ArgumentParser(description="PIP-II virtual accelerator GUI")
    ap.add_argument("--redis", default=None,
                    help="redis URL (default redis://localhost:6379/0)")
    args = ap.parse_args()
    settings = Settings(**({"redis_url": args.redis} if args.redis else {}))

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    hub = DataHub(settings=settings)
    hub.start()
    win = MainWindow(hub)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
