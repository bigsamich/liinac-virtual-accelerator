"""DVR transport bar: pause / step / rewind the simulation through the last
5 s (100 frames at 20 Hz). Pause stops the master clock; the slider replays
buffered stream history across every page."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSlider,
                             QWidget)

from . import theme

_FRAMES = 100          # 5 s at 20 Hz
_HZ = 20.0


class PlaybackBar(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._live = True
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)

        self.btn_play = QPushButton("⏸ Pause")
        self.btn_play.setFixedWidth(90)
        self.btn_step = QPushButton("⏭ Step")
        self.btn_step.setFixedWidth(70)
        self.btn_step.setEnabled(False)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, _FRAMES - 1)
        self.slider.setValue(_FRAMES - 1)          # right edge = live
        self.slider.setEnabled(False)
        self.lbl = QLabel("● LIVE")
        self.lbl.setFixedWidth(120)
        self.lbl.setStyleSheet(f"color:{theme.OK}; font-weight:bold;")

        lay.addWidget(QLabel("Sim:"))
        lay.addWidget(self.btn_play)
        lay.addWidget(self.btn_step)
        lay.addWidget(QLabel("−5 s"))
        lay.addWidget(self.slider, 1)
        lay.addWidget(QLabel("now"))
        lay.addWidget(self.lbl)

        self.btn_play.clicked.connect(self._toggle)
        self.btn_step.clicked.connect(self._step)
        self.slider.valueChanged.connect(self._scrub)

    # ------------------------------------------------------------------
    def _toggle(self):
        self._live = not self._live
        self.hub.set_running(self._live)
        if self._live:
            self.btn_play.setText("⏸ Pause")
            self.btn_step.setEnabled(False)
            self.slider.setEnabled(False)
            self.slider.blockSignals(True)
            self.slider.setValue(_FRAMES - 1)
            self.slider.blockSignals(False)
            self.lbl.setText("● LIVE")
            self.lbl.setStyleSheet(f"color:{theme.OK}; font-weight:bold;")
        else:
            self.btn_play.setText("▶ Play")
            self.btn_step.setEnabled(True)
            self.slider.setEnabled(True)
            # snap to the live edge, then a moment later replay it (the clock
            # has stopped, so the buffer is now static and scrubbable)
            self.slider.blockSignals(True)
            self.slider.setValue(_FRAMES - 1)
            self.slider.blockSignals(False)
            QTimer.singleShot(120, lambda: self._show(0))

    def _step(self):
        self.hub.step_once()
        self.slider.blockSignals(True)
        self.slider.setValue(_FRAMES - 1)
        self.slider.blockSignals(False)
        QTimer.singleShot(120, lambda: self._show(0))

    def _scrub(self, v: int):
        if self._live:
            return
        self._show(_FRAMES - 1 - v)             # right = 0 frames back = now

    def _show(self, offset: int):
        self.hub.seek(offset)
        if offset == 0:
            self.lbl.setText("⏸ PAUSED · now")
        else:
            self.lbl.setText(f"⏸ PAUSED · −{offset / _HZ:.2f} s")
        self.lbl.setStyleSheet(f"color:{theme.WARN}; font-weight:bold;")
