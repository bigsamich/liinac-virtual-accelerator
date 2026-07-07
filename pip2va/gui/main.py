"""PIP-II Virtual Accelerator control-room GUI (PyQt6 + pyqtgraph)."""
from __future__ import annotations

import argparse
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout,
                             QLabel, QMainWindow, QPushButton,
                             QStackedWidget, QStatusBar, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

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
        from .pages.section import SectionPage
        pages = load_all()

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_banner())
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.nav = QTreeWidget()
        self.nav.setFixedWidth(190)
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(12)
        self.stack = QStackedWidget()
        lay.addWidget(self.nav)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.stack, 1)
        from .askpanel import AskPanel
        self.ask_panel = AskPanel(self.hub)
        right.addWidget(self.ask_panel)
        lay.addLayout(right, 1)
        outer.addLayout(lay, 1)
        self.setCentralWidget(central)

        self._page_classes = list(pages.items())
        self._section_cls = SectionPage
        self._section_pages: dict[str, QWidget] = {}
        self._built: dict[int, QWidget] = {}
        GROUPS = [
            ("Overview", ["Dashboard"]),
            ("Instrumentation", ["Orbit", "Losses", "Profiles",
                                 "Scope", "Bunch Monitor",
                                 "Strip Tool"]),
            ("RF & Magnets", ["RF", "Magnets", "Source & LEBT"]),
            ("Operations", ["Studies", "Training", "Snapshots", "MPS"]),
            ("Machine", ["Physics", "Utilities"]),
        ]
        row_of = {lbl: i for i, (lbl, _) in enumerate(self._page_classes)}
        self._nav_items: dict[str, QTreeWidgetItem] = {}
        placed = set()
        from PyQt6.QtCore import Qt as _Qt
        def add_leaf(parent, label):
            it = QTreeWidgetItem(parent, [label])
            it.setData(0, _Qt.ItemDataRole.UserRole, row_of[label])
            self._nav_items[label] = it
            placed.add(label)
        for gname, members in GROUPS:
            present = [m for m in members if m in row_of]
            if not present:
                continue
            g = QTreeWidgetItem(self.nav, [gname])
            g.setFlags(g.flags() & ~_Qt.ItemFlag.ItemIsSelectable)
            f = g.font(0); f.setBold(True); g.setFont(0, f)
            for m in present:
                add_leaf(g, m)
        rest = [lbl for lbl, _ in self._page_classes if lbl not in placed]
        for m in rest:
            add_leaf(self.nav, m)
        self.nav.expandAll()
        if not self._page_classes:
            self.stack.addWidget(QLabel("No pages registered"))
        self.nav.currentItemChanged.connect(self._nav_changed)

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
            self.nav.setCurrentItem(self._nav_items["Dashboard"])

    def _build_banner(self) -> QWidget:
        """Always-visible permit strip: state, reset, rescue, autotune."""
        bar = QFrame()
        bar.setObjectName("panel")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 12, 6)
        self.banner_led = Led(theme.WARN, size=18)
        self.banner_lbl = QLabel("BEAM PERMIT: —")
        self.banner_lbl.setStyleSheet("font-size:15px; font-weight:bold;")
        self.btn_permit = QPushButton("RESET PERMIT")
        self.btn_permit.clicked.connect(self.hub.mps_reset)
        self.btn_rescue = QPushButton("RESCUE (restore design)")
        self.btn_rescue.setObjectName("danger")
        self.btn_rescue.clicked.connect(self.hub.rescue)
        self.chk_autotune = QCheckBox("Auto-tune orbit")
        self.chk_autotune.toggled.connect(self.hub.set_autotune)
        self.lbl_tune = QLabel("")
        self.lbl_tune.setStyleSheet("color:#8b96a5;")
        lay.addWidget(self.banner_led)
        lay.addWidget(self.banner_lbl)
        lay.addStretch(1)
        lay.addWidget(self.lbl_tune)
        lay.addWidget(self.chk_autotune)
        lay.addWidget(self.btn_rescue)
        lay.addWidget(self.btn_permit)
        return bar

    def _nav_changed(self, item, _prev):
        if item is None:
            return
        from PyQt6.QtCore import Qt as _Qt
        row = item.data(0, _Qt.ItemDataRole.UserRole)
        if row is not None:
            self._show_page(int(row))

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
        it = self._nav_items.get(label)
        if it is not None:
            self.nav.setCurrentItem(it)

    def goto_section(self, name: str):
        """Open a section view in place (not in the nav list)."""
        if name not in self._section_pages:
            w = self._section_cls(self.hub, self.lat, name)
            if hasattr(w, "backRequested"):
                w.backRequested.connect(lambda: self.goto("Dashboard"))
            self._section_pages[name] = w
            self.stack.addWidget(w)
        self.nav.clearSelection()
        self.nav.setCurrentItem(None)
        self.stack.setCurrentWidget(self._section_pages[name])

    def _on_state(self, st: dict):
        if not st:
            return
        self.lbl_pulse.setText(f"pulse {int(st.get('pulse_id', 0))}")
        self.lbl_w.setText(f"W {st.get('w_out', 0):.1f} MeV")
        self.lbl_t.setText(f"T {100 * st.get('transmission', 0):.1f} %")
        ok = bool(st.get("permit"))
        self.led_permit.set_color(theme.OK if ok else theme.ALARM)
        self.banner_led.set_color(theme.OK if ok else theme.ALARM)
        self.banner_lbl.setText(
            "BEAM PERMIT: ENABLED" if ok else "BEAM PERMIT: INHIBITED — "
            "see MPS page for analysis")
        self.banner_lbl.setStyleSheet(
            f"font-size:15px; font-weight:bold; "
            f"color:{theme.OK if ok else theme.ALARM};")
        tune = self.hub.get_state("autotune")
        if tune:
            status = tune.get("status", "")
            rms = tune.get("orbit_rms_um", -1)
            txt = f"autotune: {status}"
            if isinstance(rms, float) and rms >= 0:
                txt += f" (orbit rms {rms:.0f} µm)"
            self.lbl_tune.setText(txt)

    def closeEvent(self, ev):
        self.hub.stop()
        super().closeEvent(ev)


def main():
    ap = argparse.ArgumentParser(description="PIP-II virtual accelerator GUI")
    ap.add_argument("--redis", default=None,
                    help="redis URL (default redis://localhost:6379/0)")
    args = ap.parse_args()
    settings = Settings(**({"redis_url": args.redis} if args.redis else {}))

    import os
    if os.environ.get("PIP2VA_SOFT_GL"):
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    hub = DataHub(settings=settings)
    hub.start()
    win = MainWindow(hub)
    import os as _os
    if _os.environ.get("PIP2VA_MAXIMIZE"):
        # no window manager in the headless container -> showMaximized is
        # not honored; pin the window to exactly fill the virtual screen
        geo = app.primaryScreen().geometry()
        win.setGeometry(geo)
        win.show()
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
