"""Small shared widgets: LED, big-number readout, machine section strip."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from . import theme


class Led(QWidget):
    def __init__(self, color=theme.OK, size=14):
        super().__init__()
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def set_color(self, color: str):
        if self._color != QColor(color):
            self._color = QColor(color)
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, self._size, self._size)
        p.end()


class BigValue(QFrame):
    """Panel with a caption and a large numeric readout."""

    def __init__(self, caption: str, unit: str = "", fmt: str = "{:.2f}"):
        super().__init__()
        self.setObjectName("panel")
        self.fmt = fmt
        self.unit = unit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        cap = QLabel(caption)
        cap.setStyleSheet("color:#8b96a5;")
        self.val = QLabel("—")
        self.val.setObjectName("bigNumber")
        lay.addWidget(cap)
        lay.addWidget(self.val)

    def set(self, value, color: str | None = None):
        try:
            txt = self.fmt.format(value)
        except (TypeError, ValueError):
            txt = str(value)
        self.val.setText(f"{txt} {self.unit}".strip())
        if color:
            self.val.setStyleSheet(f"color:{color}; font-size:26px; "
                                   f"font-weight:bold;")


class SectionStrip(QWidget):
    """Clickable schematic strip of the machine sections."""

    sectionClicked = pyqtSignal(str)

    def __init__(self, sections: list[str]):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.buttons: dict[str, QPushButton] = {}
        for name in sections:
            b = QPushButton(name)
            c = theme.SECTION_COLORS.get(name, "#555")
            b.setStyleSheet(f"background:{c}; font-weight:bold; padding:8px;")
            b.clicked.connect(lambda _, n=name: self.sectionClicked.emit(n))
            lay.addWidget(b, 1)
            self.buttons[name] = b

    def set_health(self, name: str, ok: bool):
        b = self.buttons.get(name)
        if b:
            c = theme.SECTION_COLORS.get(name, "#555") if ok else theme.ALARM
            b.setStyleSheet(f"background:{c}; font-weight:bold; padding:8px;")
