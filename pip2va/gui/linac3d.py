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
    "rfgap":    (1.00, 0.55, 0.10, 1.0),
    "rfq":      (1.00, 0.35, 0.10, 1.0),
    "quad":     (0.25, 0.55, 1.00, 1.0),
    "solenoid": (0.15, 0.80, 0.90, 1.0),
    "dipole":   (0.90, 0.25, 0.85, 1.0),
    "corrector": (0.85, 0.85, 0.25, 1.0),
    "wire_scanner": (0.75, 0.75, 0.78, 1.0),
    "toroid":   (0.10, 0.95, 0.40, 1.0),
    "bpm":      (0.55, 1.00, 0.65, 1.0),
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


# shape per type: (kind, args) — sizes exaggerated for 200 m viewing scale
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
}
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
        self.show_values = values
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
        sel = (lambda e: section is None or e.section == section)

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

        # solid geometry: one merged mesh per element family
        for typ, col in TYPE_COLORS.items():
            els = [e for e in lat.elements if e.type == typ and sel(e)]
            if not els:
                continue
            VV, FF, off = [], [], 0
            for e in els:
                kind, kw = TYPE_SHAPES[typ]
                L = max(e.length, 0.35)
                if kind == "cyl":
                    v, f = _cyl(kw["radius"], L)
                else:
                    v, f = _box(L, kw["ly"], kw["lz"])
                th = headings[idx[id(e)]]
                R = np.array([[math.cos(th), -math.sin(th), 0],
                              [math.sin(th), math.cos(th), 0],
                              [0, 0, 1]])
                v = v @ R.T
                v[:, 0] += centers[idx[id(e)]][0]
                v[:, 1] += centers[idx[id(e)]][1]
                VV.append(v)
                FF.append(f + off)
                off += len(v)
            md = gl.MeshData(vertexes=np.vstack(VV), faces=np.vstack(FF))
            mesh = gl.GLMeshItem(meshdata=md, color=col, shader="shaded",
                                 smooth=False, computeNormals=True)
            self.view.addItem(mesh)

        # BPMs: live markers displaced by the orbit (global-index slices)
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

        # loss spikes at BLMs (global-index slices)
        blm_all = lat.instruments("blm")
        self._blm_g = np.array([j for j, e in enumerate(blm_all) if sel(e)])
        self.blms = [blm_all[j] for j in self._blm_g]
        self._blm_base = np.array(
            [[*centers[idx[id(e)]], 0.0] for e in self.blms])
        seg = np.repeat(self._blm_base, 2, axis=0)
        self.loss_spikes = gl.GLLinePlotItem(
            pos=seg, color=(1.0, 0.25, 0.2, 0.95), width=2.5,
            mode="lines", antialias=True)
        self.view.addItem(self.loss_spikes)

        # live 3D beam: 2-sigma envelope tube + macroparticle cloud
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
            meshdata=gl.MeshData(
                vertexes=np.zeros((nr * nv, 3)), faces=self._env_faces),
            color=(0.15, 0.9, 0.55, 0.22), shader="shaded", smooth=True,
            glOptions="additive", computeNormals=True)
        self.view.addItem(self.env_mesh)
        self.cloud = gl.GLScatterPlotItem(
            pos=np.zeros((1, 3)), color=(0.4, 0.9, 1.0, 0.35), size=2.0,
            pxMode=True)
        self.view.addItem(self.cloud)
        self._el_index = {e.name: k for k, e in enumerate(lat.elements)}

        # floating live-value labels over elements (section views)
        self.labels = {}
        if values:
            try:
                for e in lat.elements:
                    if not sel(e) or e.type == "drift" or \
                            e.type in ("aperture", "chopper", "source"):
                        continue
                    c = centers[idx[id(e)]]
                    t = gl.GLTextItem(
                        pos=(float(c[0]), float(c[1]), 2.0),
                        text=e.name.split(":")[1],
                        color=(190, 200, 215, 220))
                    self.view.addItem(t)
                    self.labels[e.name] = t
            except Exception:
                self.labels = {}

        # section markers along the line
        try:
            for s in (lat.sections if section is None else []):
                k = np.searchsorted(self._beam_s, s.s_start)
                k = min(k, len(pts) - 1)
                t = gl.GLTextItem(pos=pts[k] + [0, 2.5, 3.0], text=s.name,
                                  color=(200, 210, 225, 255))
                self.view.addItem(t)
        except Exception:
            pass

        if section is None:
            cs = centers
            dist = 95
        else:
            cs = np.array([centers[idx[id(e)]]
                           for e in lat.elements if sel(e)])
            span = float(np.ptp(cs[:, 0])) + float(np.ptp(cs[:, 1]))
            dist = max(12.0, span * 0.62)
        cx, cy = cs[:, 0].mean(), cs[:, 1].mean()
        from PyQt6.QtGui import QVector3D
        self.view.opts["center"] = QVector3D(float(cx), float(cy), 0.0)
        self.view.setCameraPosition(distance=dist, elevation=32, azimuth=-88)

    # ---------------------------------------------------------- live updates

    def update_orbit(self, x_mm, y_mm):
        """Full-machine arrays; slices to this view's BPMs."""
        if self.view is None or not self.isVisible():
            return
        g = self._bpm_g[self._bpm_g < len(x_mm)]
        x = np.asarray(x_mm)[g][:, None]
        d = (self._bpm_base[:len(g)] + self._bpm_norm[:len(g)]
             * (x * ORBIT_EXAG))
        d[:, 2] = np.asarray(y_mm)[g] * ORBIT_EXAG
        self.bpm_dots.setData(pos=d)
        if self.labels:
            for k, j in enumerate(g):
                lb = self.labels.get(self.bpms[k].name)
                if lb is not None:
                    lb.setData(text=f"{self.bpms[k].name.split(':')[1]} "
                                    f"{x_mm[j]:+.2f}/{y_mm[j]:+.2f}mm")

    def update_losses(self, wpm):
        """Full-machine array; slices to this view's BLMs."""
        if self.view is None or not self.isVisible():
            return
        g = self._blm_g[self._blm_g < len(wpm)]
        w = np.maximum(np.asarray(wpm)[g], 0.0)
        h = LOSS_SCALE * np.log10(1.0 + w)
        seg = np.repeat(self._blm_base[:len(g)], 2, axis=0)
        seg[1::2, 2] = h
        self.loss_spikes.setData(pos=seg)
        if self.labels:
            for k in range(len(g)):
                lb = self.labels.get(self.blms[k].name)
                if lb is not None:
                    lb.setData(text=f"{self.blms[k].name.split(':')[1]} "
                                    f"{w[k]:.1f}W/m")

    def update_envelope(self, cx, cy, sx, sy):
        """Full-machine per-element centroid+sigma arrays [m] -> 2-sigma
        tube, exaggerated by ORBIT_EXAG (m display per mm real)."""
        if self.view is None or not self.isVisible():
            return
        ex = ORBIT_EXAG * 1e3          # m -> display m
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
        """Macroparticle cloud (3,N) in metres at a station: drawn at the
        station's floor position, transverse exaggerated like the orbit."""
        if self.view is None or not self.isVisible() or cloud is None:
            return
        k = self._el_index.get(station_name)
        if k is None:
            return
        c = np.asarray(cloud)
        if c.shape[0] != 3:
            c = c.T
        n = c.shape[1]
        if n > max_pts:
            c = c[:, :: max(1, n // max_pts)]
        ex = ORBIT_EXAG * 1e3
        th = self.headings[k]
        d = np.array([math.cos(th), math.sin(th)])
        nn = np.array([-math.sin(th), math.cos(th)])
        base = self.centers[k]
        along = c[2] * 4.0                 # z: metres, x4 to show the bunch
        P = np.empty((c.shape[1], 3))
        P[:, 0] = base[0] + d[0] * along + nn[0] * c[0] * ex
        P[:, 1] = base[1] + d[1] * along + nn[1] * c[0] * ex
        P[:, 2] = c[1] * ex
        self.cloud.setData(pos=P)

    def update_values(self, mapping):
        """Set floating label text for named elements: {name: text}."""
        if not self.labels:
            return
        for name, txt in mapping.items():
            lb = self.labels.get(name)
            if lb is not None:
                lb.setData(text=txt)

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
