"""Live 3D synoptic of the full linac + BTL.

Floor plan from the lattice (BTL dipole bends included), every element as a
colored marker, BPMs displaced by the live orbit (exaggerated), red loss
spikes at each BLM scaled to W/m, and the beamline colored by the live
current profile from the BCMs.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

TYPE_COLORS = {
    "rfgap":    (1.00, 0.60, 0.10, 0.9),
    "rfq":      (1.00, 0.40, 0.10, 1.0),
    "quad":     (0.25, 0.55, 1.00, 0.9),
    "solenoid": (0.20, 0.85, 0.90, 0.9),
    "dipole":   (0.95, 0.30, 0.85, 1.0),
    "corrector": (0.85, 0.85, 0.30, 0.6),
    "wire_scanner": (0.70, 0.70, 0.70, 0.7),
    "toroid":   (0.10, 0.95, 0.40, 0.9),
}
TYPE_SIZES = {"rfgap": 6, "rfq": 10, "quad": 6, "solenoid": 7, "dipole": 10,
              "corrector": 4, "wire_scanner": 4, "toroid": 6}
ORBIT_EXAG = 0.25       # metres of display per mm of orbit
LOSS_SCALE = 2.0        # spike height = LOSS_SCALE * log10(1 + W/m)


def floor_map(lat):
    """Walk the lattice: each element centre -> (x, y) floor position and
    heading angle. Dipoles bend the heading by angle_deg."""
    x = y = th = 0.0
    centers, headings = [], []
    poly = [(0.0, 0.0)]
    for e in lat.elements:
        ang = math.radians(e.params.get("angle_deg", 0.0)) \
            if e.type == "dipole" else 0.0
        # advance half the length, record centre (with half the bend)
        th_c = th + ang / 2.0
        cx = x + math.cos(th_c) * e.length / 2.0
        cy = y + math.sin(th_c) * e.length / 2.0
        centers.append((cx, cy))
        headings.append(th_c)
        x += math.cos(th_c) * e.length
        y += math.sin(th_c) * e.length
        th += ang
        if e.length > 0:
            poly.append((x, y))
    return np.array(centers), np.array(headings), np.array(poly)


class Linac3D(QWidget):
    def __init__(self, lat, parent=None):
        super().__init__(parent)
        self.lat = lat
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            import pyqtgraph.opengl as gl
            self.gl = gl
        except Exception as e:
            lay.addWidget(QLabel(f"3D view unavailable: {e}"))
            self.view = None
            return
        self.view = gl.GLViewWidget()
        lay.addWidget(self.view)

        centers, headings, poly = floor_map(lat)
        self.centers, self.headings = centers, headings
        idx = {id(e): k for k, e in enumerate(lat.elements)}

        grid = gl.GLGridItem()
        grid.setSize(240, 120)
        grid.setSpacing(10, 10)
        grid.translate(90, 0, -0.6)
        self.view.addItem(grid)

        # centreline + live-current overlay
        pts = np.column_stack([poly[:, 0], poly[:, 1],
                               np.zeros(len(poly))])
        self.view.addItem(gl.GLLinePlotItem(
            pos=pts, color=(0.45, 0.5, 0.55, 0.8), width=1.2,
            antialias=True))
        self._beam_pts = pts
        self._beam_s = np.concatenate([[0.0], np.cumsum(
            np.linalg.norm(np.diff(poly, axis=0), axis=1))])
        self.beam_line = gl.GLLinePlotItem(
            pos=pts + [0, 0, 0.02],
            color=np.tile((0.1, 1.0, 0.3, 0.9), (len(pts), 1)),
            width=3.5, antialias=True)
        self.view.addItem(self.beam_line)

        # static elements, one scatter per type
        for typ, col in TYPE_COLORS.items():
            els = [e for e in lat.elements if e.type == typ]
            if not els:
                continue
            pos = np.array([[*centers[idx[id(e)]], 0.0] for e in els])
            self.view.addItem(gl.GLScatterPlotItem(
                pos=pos, color=col, size=TYPE_SIZES.get(typ, 5),
                pxMode=True))

        # BPMs: live markers displaced by the orbit
        self.bpms = lat.instruments("bpm")
        self._bpm_base = np.array(
            [[*centers[idx[id(e)]], 0.0] for e in self.bpms])
        self._bpm_norm = np.array(
            [[-math.sin(headings[idx[id(e)]]),
              math.cos(headings[idx[id(e)]]), 0.0] for e in self.bpms])
        self.bpm_dots = gl.GLScatterPlotItem(
            pos=self._bpm_base, color=(0.2, 1.0, 0.5, 1.0), size=8,
            pxMode=True)
        self.view.addItem(self.bpm_dots)

        # loss spikes at BLMs
        self.blms = lat.instruments("blm")
        self._blm_base = np.array(
            [[*centers[idx[id(e)]], 0.0] for e in self.blms])
        seg = np.repeat(self._blm_base, 2, axis=0)
        self.loss_spikes = gl.GLLinePlotItem(
            pos=seg, color=(1.0, 0.25, 0.2, 0.95), width=2.5,
            mode="lines", antialias=True)
        self.view.addItem(self.loss_spikes)

        # section markers along the line
        try:
            for s in lat.sections:
                k = np.searchsorted(self._beam_s, s.s_start)
                k = min(k, len(pts) - 1)
                t = gl.GLTextItem(pos=pts[k] + [0, 2.5, 3.0], text=s.name,
                                  color=(200, 210, 225, 255))
                self.view.addItem(t)
        except Exception:
            pass

        cx, cy = centers[:, 0].mean(), centers[:, 1].mean()
        from PyQt6.QtGui import QVector3D
        self.view.opts["center"] = QVector3D(float(cx), float(cy), 0.0)
        self.view.setCameraPosition(distance=95, elevation=32, azimuth=-88)

    # ---------------------------------------------------------- live updates

    def update_orbit(self, x_mm, y_mm):
        if self.view is None or not self.isVisible():
            return
        n = min(len(x_mm), len(self._bpm_base))
        d = (self._bpm_base[:n]
             + self._bpm_norm[:n] * (x_mm[:n, None] * ORBIT_EXAG))
        d[:, 2] = y_mm[:n] * ORBIT_EXAG
        self.bpm_dots.setData(pos=d)

    def update_losses(self, wpm):
        if self.view is None or not self.isVisible():
            return
        n = min(len(wpm), len(self._blm_base))
        h = LOSS_SCALE * np.log10(1.0 + np.maximum(wpm[:n], 0.0))
        seg = np.repeat(self._blm_base[:n], 2, axis=0)
        seg[1::2, 2] = h
        self.loss_spikes.setData(pos=seg)

    def update_current(self, i_ma, tor_s):
        if self.view is None or not self.isVisible():
            return
        idxs = np.searchsorted(tor_s, self._beam_s) - 1
        idxs = np.clip(idxs, 0, len(i_ma) - 1)
        frac = np.clip(np.asarray(i_ma)[idxs] / 5.0, 0.0, 1.0)
        col = np.zeros((len(self._beam_pts), 4))
        col[:, 0] = 0.1
        col[:, 1] = 0.25 + 0.75 * frac
        col[:, 2] = 0.2
        col[:, 3] = 0.25 + 0.75 * frac
        self.beam_line.setData(color=col)
