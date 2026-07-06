"""Live 3D synoptic of the linac + BTL (full machine or one section).

- True floor plan (BTL dipole bends), solid geometry per element family.
- Live beam: BPM markers on the orbit, 2-sigma envelope tube, macro cloud,
  red loss spikes, current-glow beamline.
- Ghost: the last 100 pulses of BPM orbit positions in grey.
- Camera: Top/Side/End/Iso buttons + XYZ gizmo; wheel zooms to the center
  point; TRIPLE-CLICK anywhere moves the center (and so the zoom target).
- Hover: a readout panel names the nearest elements (BPM / BLM / BCM plus
  the nearest powered element) and their live values - no overlapping
  floating text.
"""
from __future__ import annotations

import collections
import math
import time

import numpy as np
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

TYPE_COLORS = {
    "rfgap":    (1.00, 0.55, 0.10, 1.0),
    "rfq":      (1.00, 0.35, 0.10, 1.0),
    "quad":     (0.25, 0.55, 1.00, 1.0),
    "solenoid": (0.15, 0.80, 0.90, 1.0),
    "dipole":   (0.90, 0.25, 0.85, 1.0),
    "corrector": (0.85, 0.85, 0.25, 1.0),
    "wire_scanner": (0.75, 0.75, 0.78, 1.0),
    "toroid":   (0.10, 0.95, 0.40, 1.0),
    "bpm":      (0.55, 1.00, 0.65, 1.0),
    "valve":    (0.55, 0.58, 0.62, 1.0),
    "skew_quad": (0.55, 0.35, 0.95, 1.0),
    "halo":     (0.95, 0.75, 0.30, 1.0),
    "bsm":      (0.80, 0.55, 0.95, 1.0),
    "septum":   (1.00, 0.25, 0.35, 1.0),
    "orbump":   (1.00, 0.45, 0.15, 1.0),
    "foil":     (0.95, 0.95, 0.95, 1.0),
    "sweep":    (0.90, 0.20, 0.60, 1.0),
    "scraper2": (0.75, 0.45, 0.20, 1.0),
    "allison":  (0.30, 0.90, 0.75, 1.0),
    "ffc":      (0.95, 0.85, 0.40, 1.0),
    "eid":      (0.50, 0.50, 0.80, 1.0),
    "absorber": (0.45, 0.30, 0.25, 1.0),
    "dpi":      (0.40, 0.60, 0.60, 1.0),
    "rfsep":    (1.00, 0.50, 0.60, 1.0),
    "mwpm":     (0.65, 0.85, 0.55, 1.0),
}


def _cyl(radius, length, cols=10):
    """Cylinder along +x, centred at origin: (verts, faces)."""
    a = np.linspace(0, 2 * np.pi, cols, endpoint=False)
    ring = np.column_stack([np.cos(a), np.sin(a)]) * radius
    v0 = np.column_stack([np.full(cols, -length / 2), ring])
    v1 = np.column_stack([np.full(cols, +length / 2), ring])
    V = np.vstack([v0, v1, [[-length / 2, 0, 0]], [[length / 2, 0, 0]]])
    F = []
    for k in range(cols):
        k2 = (k + 1) % cols
        F += [[k, cols + k, cols + k2], [k, cols + k2, k2],
              [2 * cols, k2, k], [2 * cols + 1, cols + k, cols + k2]]
    return V, np.array(F)


def _box(lx, ly, lz):
    x, y, z = lx / 2, ly / 2, lz / 2
    V = np.array([[-x, -y, -z], [x, -y, -z], [x, y, -z], [-x, y, -z],
                  [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z]])
    F = np.array([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6],
                  [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2],
                  [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])
    return V, F


TYPE_SHAPES = {
    "rfgap":    ("cyl", dict(radius=0.55)),
    "rfq":      ("box", dict(ly=1.1, lz=1.1)),
    "quad":     ("box", dict(ly=0.9, lz=0.9)),
    "solenoid": ("cyl", dict(radius=0.75)),
    "dipole":   ("box", dict(ly=1.6, lz=0.7)),
    "corrector": ("box", dict(ly=0.55, lz=0.55)),
    "wire_scanner": ("box", dict(ly=0.35, lz=1.4)),
    "toroid":   ("cyl", dict(radius=0.85)),
    "bpm":      ("cyl", dict(radius=0.42)),
    "valve":    ("box", dict(ly=1.0, lz=1.0)),
    "skew_quad": ("box", dict(ly=0.9, lz=0.9)),
    "halo":     ("cyl", dict(radius=0.5)),
    "bsm":      ("box", dict(ly=0.5, lz=1.2)),
    "septum":   ("box", dict(ly=1.8, lz=0.8)),
    "orbump":   ("box", dict(ly=1.4, lz=0.6)),
    "foil":     ("box", dict(ly=1.2, lz=1.2)),
    "sweep":    ("box", dict(ly=1.5, lz=0.7)),
    "scraper2": ("box", dict(ly=0.4, lz=0.4)),
    "allison":  ("box", dict(ly=0.8, lz=1.3)),
    "ffc":      ("cyl", dict(radius=0.4)),
    "eid":      ("cyl", dict(radius=0.55)),
    "absorber": ("box", dict(ly=1.3, lz=1.3)),
    "dpi":      ("cyl", dict(radius=0.6)),
    "rfsep":    ("box", dict(ly=1.2, lz=0.9)),
    "mwpm":     ("box", dict(ly=0.35, lz=1.1)),
}
ORBIT_EXAG = 0.25       # display metres per mm of beam coordinate
LOSS_SCALE = 2.0        # spike height = LOSS_SCALE * log10(1 + W/m)
GHOST_PULSES = 100


def floor_map(lat):
    """Walk the lattice: element centre -> (x, y) floor position + heading.
    Dipoles bend the heading by angle_deg."""
    x = y = th = 0.0
    centers, headings = [], []
    poly = [(0.0, 0.0)]
    for e in lat.elements:
        ang = math.radians(e.params.get("angle_deg", 0.0)) \
            if e.type == "dipole" else 0.0
        th_c = th - ang / 2.0
        cx = x + math.cos(th_c) * e.length / 2.0
        cy = y + math.sin(th_c) * e.length / 2.0
        centers.append((cx, cy))
        headings.append(th_c)
        x += math.cos(th_c) * e.length
        y += math.sin(th_c) * e.length
        th -= ang
        if e.length > 0:
            poly.append((x, y))
    return np.array(centers), np.array(headings), np.array(poly)


class Linac3D(QWidget):
    def __init__(self, lat, parent=None, section=None, values=False):
        super().__init__(parent)
        self.lat = lat
        self.section = section
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        try:
            import pyqtgraph.opengl as gl
            self.gl = gl
        except Exception as e:
            lay.addWidget(QLabel(f"3D view unavailable: {e}"))
            self.view = None
            return

        # ---- control bar: ghost toggle + camera presets + hover readout
        bar = QHBoxLayout()
        self.chk_ghost = QCheckBox(f"ghost ({GHOST_PULSES} pulses)")
        bar.addWidget(self.chk_ghost)
        for nm in ("Top", "Side", "End", "Iso"):
            b = QPushButton(nm)
            b.setFixedWidth(44)
            b.clicked.connect(lambda _, n=nm: self._preset(n))
            bar.addWidget(b)
        if section is None:
            from PyQt6.QtWidgets import QComboBox
            bar.addWidget(QLabel(" zoom:"))
            self.sel_zoom = QComboBox()
            self.sel_zoom.addItem("full machine")
            self.sel_zoom.addItems([s.name for s in lat.sections])
            self.sel_zoom.currentTextChanged.connect(self._zoom_section)
            bar.addWidget(self.sel_zoom)
        self.lbl_hover = QLabel("hover for nearby BPM/BLM/BCM; "
                                "triple-click moves the zoom center")
        self.lbl_hover.setStyleSheet(
            "color:#cfd8e3; background:#161b22; padding:2px 6px;")
        bar.addWidget(self.lbl_hover, 1)
        lay.addLayout(bar)

        self.view = gl.GLViewWidget()
        self.view.installEventFilter(self)
        self.view.setMouseTracking(True)
        lay.addWidget(self.view, 1)

        centers, headings, poly = floor_map(lat)
        self.centers, self.headings = centers, headings
        idx = {id(e): k for k, e in enumerate(lat.elements)}
        sel = (lambda e: section is None or e.section == section)

        grid = gl.GLGridItem()
        grid.setSize(240, 120)
        grid.setSpacing(10, 10)
        grid.translate(90, 0, -0.6)
        self.view.addItem(grid)

        # XYZ gizmo
        ax = gl.GLAxisItem()
        ax.setSize(6, 6, 6)
        self.view.addItem(ax)
        try:
            for txt, pos, col in (("X", (6.6, 0, 0), (90, 140, 255, 255)),
                                  ("Y", (0, 6.6, 0), (255, 220, 90, 255)),
                                  ("Z", (0, 0, 6.6), (110, 255, 130, 255))):
                self.view.addItem(gl.GLTextItem(pos=pos, text=txt,
                                                color=col))
        except Exception:
            pass

        pts = np.column_stack([poly[:, 0], poly[:, 1], np.zeros(len(poly))])
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

        # solid geometry: one merged mesh per element family
        for typ, col in TYPE_COLORS.items():
            els = [e for e in lat.elements if e.type == typ and sel(e)]
            if not els:
                continue
            VV, FF, off = [], [], 0
            for e in els:
                kind, kw = TYPE_SHAPES[typ]
                L = max(e.length, 0.35)
                v, f = (_cyl(kw["radius"], L) if kind == "cyl"
                        else _box(L, kw["ly"], kw["lz"]))
                if typ == "skew_quad":     # rotated 45 deg about beam axis
                    c45 = math.cos(math.pi / 4)
                    Rx = np.array([[1, 0, 0], [0, c45, -c45], [0, c45, c45]])
                    v = v @ Rx.T
                th = headings[idx[id(e)]]
                R = np.array([[math.cos(th), -math.sin(th), 0],
                              [math.sin(th), math.cos(th), 0], [0, 0, 1]])
                v = v @ R.T
                v[:, 0] += centers[idx[id(e)]][0]
                v[:, 1] += centers[idx[id(e)]][1]
                VV.append(v)
                FF.append(f + off)
                off += len(v)
            self.view.addItem(gl.GLMeshItem(
                meshdata=gl.MeshData(vertexes=np.vstack(VV),
                                     faces=np.vstack(FF)),
                color=col, shader="shaded", smooth=False,
                computeNormals=True))

        # hover targets: instruments + powered elements
        self._hover_els = [
            e for e in lat.elements if sel(e) and e.type in
            ("bpm", "blm", "toroid", "rfgap", "rfq", "quad", "solenoid",
             "corrector", "dipole", "wire_scanner")]
        self._hover_pos = np.array(
            [centers[idx[id(e)]] for e in self._hover_els]) \
            if self._hover_els else np.zeros((0, 2))
        self._vals: dict[str, str] = {}

        # BPM live markers + ghost trail
        bpm_all = lat.instruments("bpm")
        self._bpm_g = np.array([j for j, e in enumerate(bpm_all) if sel(e)])
        self.bpms = [bpm_all[j] for j in self._bpm_g]
        self._bpm_base = np.array(
            [[*centers[idx[id(e)]], 0.0] for e in self.bpms])
        self._bpm_norm = np.array(
            [[-math.sin(headings[idx[id(e)]]),
              math.cos(headings[idx[id(e)]]), 0.0] for e in self.bpms])
        self.bpm_dots = gl.GLScatterPlotItem(
            pos=self._bpm_base, color=(0.2, 1.0, 0.5, 1.0), size=8,
            pxMode=True)
        self.view.addItem(self.bpm_dots)
        self._ghost = collections.deque(maxlen=GHOST_PULSES)
        self.ghost_dots = gl.GLScatterPlotItem(
            pos=np.zeros((1, 3)), color=(0.6, 0.6, 0.65, 0.18), size=4,
            pxMode=True)
        self.view.addItem(self.ghost_dots)

        # loss spikes
        blm_all = lat.instruments("blm")
        self._blm_g = np.array([j for j, e in enumerate(blm_all) if sel(e)])
        self.blms = [blm_all[j] for j in self._blm_g]
        self._blm_base = np.array(
            [[*centers[idx[id(e)]], 0.0] for e in self.blms])
        seg = np.repeat(self._blm_base, 2, axis=0)
        self.loss_spikes = gl.GLLinePlotItem(
            pos=seg, color=(1.0, 0.25, 0.2, 0.95), width=2.5, mode="lines",
            antialias=True)
        self.view.addItem(self.loss_spikes)

        # envelope tube + macro cloud
        self._env_rings = [k for k, e in enumerate(lat.elements)
                           if sel(e) and e.length > 0][::3]
        nr, nv = len(self._env_rings), 10
        self._env_phi = np.linspace(0, 2 * np.pi, nv, endpoint=False)
        F = []
        for i in range(nr - 1):
            for j in range(nv):
                a, b = i * nv + j, i * nv + (j + 1) % nv
                c, d = a + nv, (i + 1) * nv + (j + 1) % nv
                F += [[a, c, d], [a, d, b]]
        self._env_faces = np.array(F)
        self.env_mesh = gl.GLMeshItem(
            meshdata=gl.MeshData(vertexes=np.zeros((nr * nv, 3)),
                                 faces=self._env_faces),
            color=(0.15, 0.9, 0.55, 0.22), shader="shaded", smooth=True,
            glOptions="additive", computeNormals=True)
        self.view.addItem(self.env_mesh)
        self.cloud = gl.GLScatterPlotItem(
            pos=np.zeros((1, 3)), color=(0.4, 0.9, 1.0, 0.35), size=2.0,
            pxMode=True)
        self.view.addItem(self.cloud)
        self._el_index = {e.name: k for k, e in enumerate(lat.elements)}

        # section markers (full-machine view only)
        try:
            for s in (lat.sections if section is None else []):
                k = min(np.searchsorted(self._beam_s, s.s_start),
                        len(pts) - 1)
                self.view.addItem(gl.GLTextItem(
                    pos=pts[k] + [0, 2.5, 3.0], text=s.name,
                    color=(200, 210, 225, 255)))
        except Exception:
            pass

        if section is None:
            cs, dist = centers, 95.0
        else:
            cs = np.array([centers[idx[id(e)]]
                           for e in lat.elements if sel(e)])
            dist = max(12.0, (float(np.ptp(cs[:, 0]))
                              + float(np.ptp(cs[:, 1]))) * 0.62)
        from PyQt6.QtGui import QVector3D
        self._home = (QVector3D(float(cs[:, 0].mean()),
                                float(cs[:, 1].mean()), 0.0), dist)
        self.view.opts["center"] = self._home[0]
        self.view.setCameraPosition(distance=dist, elevation=32,
                                    azimuth=-88)
        self._clicks: list[float] = []

    # -------------------------------------------------------------- camera

    def _zoom_section(self, name):
        from PyQt6.QtGui import QVector3D
        if name == "full machine":
            self.view.opts["center"] = self._home[0]
            self.view.setCameraPosition(distance=self._home[1])
            self.view.update()
            return
        ks = [k for k, e in enumerate(self.lat.elements)
              if e.section == name]
        if not ks:
            return
        cs = self.centers[ks]
        self.view.opts["center"] = QVector3D(
            float(cs[:, 0].mean()), float(cs[:, 1].mean()), 0.0)
        span = float(np.ptp(cs[:, 0])) + float(np.ptp(cs[:, 1]))
        self.view.setCameraPosition(distance=max(10.0, span * 0.7))
        self.view.update()

    def _preset(self, nm):
        d = self.view.opts["distance"]
        if nm == "Top":
            self.view.setCameraPosition(elevation=90, azimuth=-90,
                                        distance=d)
        elif nm == "Side":
            self.view.setCameraPosition(elevation=2, azimuth=-90,
                                        distance=d)
        elif nm == "End":
            self.view.setCameraPosition(elevation=2, azimuth=0, distance=d)
        else:
            self.view.opts["center"] = self._home[0]
            self.view.setCameraPosition(elevation=32, azimuth=-88,
                                        distance=self._home[1])

    def _unproject(self, px, py):
        """Pixel -> point on the z=0 floor plane."""
        o = self.view.opts
        az = math.radians(o["azimuth"])
        el = math.radians(o["elevation"])
        c = o["center"]
        cam = np.array([c.x() + o["distance"] * math.cos(el) * math.cos(az),
                        c.y() + o["distance"] * math.cos(el) * math.sin(az),
                        c.z() + o["distance"] * math.sin(el)])
        fwd = np.array([c.x(), c.y(), c.z()]) - cam
        fwd /= np.linalg.norm(fwd)
        right = np.cross(fwd, [0, 0, 1.0])
        n = np.linalg.norm(right)
        right = right / n if n > 1e-6 else np.array([1.0, 0, 0])
        up = np.cross(right, fwd)
        w, h = max(self.view.width(), 1), max(self.view.height(), 1)
        t = math.tan(math.radians(o.get("fov", 60)) / 2)
        dx = (2.0 * px / w - 1.0) * t * (w / h)
        dy = (1.0 - 2.0 * py / h) * t
        d = fwd + dx * right + dy * up
        d /= np.linalg.norm(d)
        if abs(d[2]) < 1e-6:
            return None
        tt = -cam[2] / d[2]
        return cam + tt * d if tt > 0 else None

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.view:
            if ev.type() == QEvent.Type.MouseMove:
                self._hover(ev.position().x(), ev.position().y())
            elif ev.type() in (QEvent.Type.MouseButtonPress,
                               QEvent.Type.MouseButtonDblClick):
                now = time.monotonic()
                self._clicks = [t for t in self._clicks if now - t < 0.6]
                self._clicks.append(now)
                if len(self._clicks) >= 3:
                    self._clicks.clear()
                    p = self._unproject(ev.position().x(),
                                        ev.position().y())
                    if p is not None:
                        # snap to the nearest element so the element itself
                        # becomes the zoom center
                        if len(self._hover_pos):
                            d2 = ((self._hover_pos[:, 0] - p[0]) ** 2
                                  + (self._hover_pos[:, 1] - p[1]) ** 2)
                            j = int(np.argmin(d2))
                            if d2[j] < 100.0:      # within 10 m: snap
                                e = self._hover_els[j]
                                p = (*self._hover_pos[j], 0.0)
                                self.lbl_hover.setText(
                                    f"centered on {e.name}   |   "
                                    + self._vals.get(e.name, ""))
                        from PyQt6.QtGui import QVector3D
                        self.view.opts["center"] = QVector3D(
                            float(p[0]), float(p[1]), 0.0)
                        self.view.update()
        return False

    def _hover(self, px, py):
        p = self._unproject(px, py)
        if p is None or not len(self._hover_pos):
            return
        d2 = ((self._hover_pos[:, 0] - p[0]) ** 2
              + (self._hover_pos[:, 1] - p[1]) ** 2)
        near = np.argsort(d2)[:10]
        if d2[near[0]] > 36.0:          # nothing within 6 m
            return
        shown, kinds = [], set()
        for j in near:
            e = self._hover_els[j]
            kind = ("bpm" if e.type == "bpm" else
                    "blm" if e.type == "blm" else
                    "bcm" if e.type == "toroid" else "dev")
            if kind in kinds:
                continue
            kinds.add(kind)
            shown.append(self._vals.get(e.name, e.name))
            if len(kinds) >= 4:
                break
        self.lbl_hover.setText("   |   ".join(shown))

    # ---------------------------------------------------------- live data

    def update_orbit(self, x_mm, y_mm):
        if self.view is None or not self.isVisible():
            return
        g = self._bpm_g[self._bpm_g < len(x_mm)]
        x = np.asarray(x_mm)[g][:, None]
        d = (self._bpm_base[:len(g)] + self._bpm_norm[:len(g)]
             * (x * ORBIT_EXAG))
        d[:, 2] = np.asarray(y_mm)[g] * ORBIT_EXAG
        self.bpm_dots.setData(pos=d)
        for k, j in enumerate(g):
            self._vals[self.bpms[k].name] = (
                f"{self.bpms[k].name} {x_mm[j]:+.2f}/{y_mm[j]:+.2f} mm")
        if self.chk_ghost.isChecked():
            self._ghost.append(d.copy())
            self.ghost_dots.setData(pos=np.vstack(self._ghost))
        elif self._ghost:
            self._ghost.clear()
            self.ghost_dots.setData(pos=np.zeros((1, 3)))

    def update_losses(self, wpm):
        if self.view is None or not self.isVisible():
            return
        g = self._blm_g[self._blm_g < len(wpm)]
        w = np.maximum(np.asarray(wpm)[g], 0.0)
        h = LOSS_SCALE * np.log10(1.0 + w)
        seg = np.repeat(self._blm_base[:len(g)], 2, axis=0)
        seg[1::2, 2] = h
        self.loss_spikes.setData(pos=seg)
        for k in range(len(g)):
            self._vals[self.blms[k].name] = (
                f"{self.blms[k].name} {w[k]:.2f} W/m")

    def update_current(self, i_ma, tor_s):
        if self.view is None or not self.isVisible():
            return
        idxs = np.clip(np.searchsorted(tor_s, self._beam_s) - 1, 0,
                       len(i_ma) - 1)
        frac = np.clip(np.asarray(i_ma)[idxs] / 5.0, 0.0, 1.0)
        col = np.zeros((len(self._beam_pts), 4))
        col[:, 0] = 0.1
        col[:, 1] = 0.25 + 0.75 * frac
        col[:, 2] = 0.2
        col[:, 3] = 0.25 + 0.75 * frac
        self.beam_line.setData(color=col)
        for j, t in enumerate(self.lat.instruments("toroid")[:len(i_ma)]):
            self._vals[t.name] = f"{t.name} {i_ma[j]:.3f} mA"

    def update_values(self, mapping):
        """Live values for the hover readout: {element name: text}."""
        self._vals.update(mapping)

    def pull_envelope(self, r):
        """Read truth:beam and refresh the 2-sigma tube."""
        if self.view is None or not self.isVisible():
            return
        blob = r.hget("truth:beam", "d")
        if blob is None:
            return
        from pip2va.common import codec
        _, tr = codec.unpack(blob)
        self.update_envelope(tr["cx"], tr["cy"], tr["sig_x"], tr["sig_y"])

    def update_envelope(self, cx, cy, sx, sy):
        if self.view is None or not self.isVisible():
            return
        ex = ORBIT_EXAG * 1e3
        ph = self._env_phi
        V = np.empty((len(self._env_rings) * len(ph), 3))
        for i, k in enumerate(self._env_rings):
            c = self.centers[k]
            n = np.array([-math.sin(self.headings[k]),
                          math.cos(self.headings[k])])
            r_t = (cx[k] + 2 * sx[k] * np.cos(ph)) * ex
            r_v = (cy[k] + 2 * sy[k] * np.sin(ph)) * ex
            V[i * len(ph):(i + 1) * len(ph), 0] = c[0] + n[0] * r_t
            V[i * len(ph):(i + 1) * len(ph), 1] = c[1] + n[1] * r_t
            V[i * len(ph):(i + 1) * len(ph), 2] = r_v
        self.env_mesh.setMeshData(meshdata=self.gl.MeshData(
            vertexes=V, faces=self._env_faces))

    def update_cloud(self, cloud, station_name, max_pts=8000):
        """Macro cloud (3,N) in mm (alive particles) at a station."""
        if self.view is None or not self.isVisible() or cloud is None:
            return
        k = self._el_index.get(station_name)
        if k is None:
            return
        c = np.asarray(cloud, dtype=float)
        if c.shape[0] != 3:
            c = c.T
        n = c.shape[1]
        if n > max_pts:
            c = c[:, :: max(1, n // max_pts)]
        th = self.headings[k]
        d = np.array([math.cos(th), math.sin(th)])
        nn = np.array([-math.sin(th), math.cos(th)])
        base = self.centers[k]
        x_mm = c[0] - np.median(c[0])
        y_mm = c[1] - np.median(c[1])
        z_mm = c[2] - np.median(c[2])
        along = z_mm * 0.02
        P = np.empty((c.shape[1], 3))
        P[:, 0] = base[0] + d[0] * along + nn[0] * x_mm * ORBIT_EXAG
        P[:, 1] = base[1] + d[1] * along + nn[1] * x_mm * ORBIT_EXAG
        P[:, 2] = y_mm * ORBIT_EXAG
        sx = np.std(x_mm) + 1e-9
        sy = np.std(y_mm) + 1e-9
        r = np.sqrt((x_mm / sx) ** 2 + (y_mm / sy) ** 2)
        col = np.tile((0.35, 0.9, 1.0, 0.35), (len(r), 1))
        col[r > 3.0] = (1.0, 0.6, 0.15, 0.5)
        self.cloud.setData(pos=P, color=col)
