"""Qt-free machine floor-plan geometry (shared by the 3D GUI and the web
gateway). Walks the lattice, bending at dipoles, returning element centres,
headings, and the centreline polyline."""
from __future__ import annotations

import math

import numpy as np

TYPE_COLORS = {
    "rfgap": (255, 140, 26), "rfq": (255, 90, 26), "quad": (64, 140, 255),
    "solenoid": (38, 204, 230), "dipole": (230, 64, 217),
    "corrector": (217, 217, 64), "wire_scanner": (191, 191, 199),
    "toroid": (26, 242, 102), "bpm": (140, 255, 166),
    "skew_quad": (140, 90, 242), "valve": (140, 148, 158),
    "halo": (242, 191, 76), "bsm": (204, 140, 242), "septum": (255, 64, 89),
    "orbump": (255, 115, 38), "foil": (242, 242, 242), "sweep": (230, 51, 153),
    "scraper2": (191, 115, 51), "allison": (76, 230, 191),
    "ffc": (242, 217, 102), "eid": (128, 128, 204), "absorber": (115, 76, 64),
    "dpi": (102, 153, 153), "rfsep": (255, 128, 153), "mwpm": (166, 217, 140),
    "pump": (90, 115, 140), "gauge": (217, 166, 242), "blm": (255, 64, 51),
    "source": (255, 200, 60),
}


def floor_map(lat):
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
