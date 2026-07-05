"""Conventional-facilities model: cryoplant 2 K circuits and LCW.

These are the slow "plant" states that couple into the electronics and RF:
- Per-cryomodule 2 K helium bath pressure (nominal 31.0 mbar saturated).
  Slow OU wander + a very slow plant breathing mode. Cavity detuning
  couples via each family's measured df/dp (e.g. SSR2 -3.4 Hz/mbar class).
- LCW supply temperature (nominal 35.0 C, regulated +/-0.6 C). Couples
  into BPM-electronics phase (TOF energy reading) and SSA gain calibration.

Fault injection via settings:util:main:
  lcw_offset_c      — add C to the LCW supply (chiller degradation)
  cryo_offset_mbar  — add mbar to one CM's bath pressure
  cryo_cm           — which CM the offset applies to (name)
Published once per second to state:util (JSON) and readback:util:* hashes.
"""
from __future__ import annotations

import json
import math

import numpy as np

# cryomodule layout: (name, section, cavity index range within section)
CRYOMODULES = [
    ("CM-HWR", "HWR", (0, 8)),
    ("CM-SSR1-1", "SSR1", (0, 8)), ("CM-SSR1-2", "SSR1", (8, 16)),
    ("CM-SSR2-1", "SSR2", (0, 7)), ("CM-SSR2-2", "SSR2", (7, 14)),
    ("CM-SSR2-3", "SSR2", (14, 21)), ("CM-SSR2-4", "SSR2", (21, 28)),
    ("CM-SSR2-5", "SSR2", (28, 35)),
    ("CM-LB650-1", "LB650", (0, 9)), ("CM-LB650-2", "LB650", (9, 18)),
    ("CM-LB650-3", "LB650", (18, 27)), ("CM-LB650-4", "LB650", (27, 36)),
    ("CM-HB650-1", "HB650", (0, 8)), ("CM-HB650-2", "HB650", (8, 16)),
    ("CM-HB650-3", "HB650", (16, 24)),
]
P_NOM_MBAR = 31.0
LCW_NOM_C = 35.0


class UtilityModel:
    def __init__(self, rng=None):
        self.rng = rng or np.random.default_rng(20260705)
        n = len(CRYOMODULES)
        self.p_mbar = np.full(n, P_NOM_MBAR)
        self.lcw_c = LCW_NOM_C
        self.t = 0.0
        self._phase = self.rng.uniform(0, 2 * math.pi, n)

    def step(self, dt: float, lcw_offset=0.0, cryo_offset=0.0, cryo_cm=""):
        self.t += dt
        n = len(CRYOMODULES)
        # 2 K bath: OU wander (tau 120 s, sigma 0.05 mbar) + plant breathing
        # (8-minute mode, +/-0.08 mbar, per-CM phase)
        a = dt / 120.0
        self.p_mbar += (-a * (self.p_mbar - P_NOM_MBAR)
                        + 0.05 * math.sqrt(2 * a) * self.rng.standard_normal(n))
        breath = 0.08 * np.sin(2 * math.pi * self.t / 480.0 + self._phase)
        p = self.p_mbar + breath
        for k, (nm, _, _) in enumerate(CRYOMODULES):
            if nm == cryo_cm:
                p[k] += cryo_offset
        # LCW: regulated 35 +/- 0.6 C — 20-min valve cycle + sensor noise
        self.lcw_c += -dt / 300.0 * (self.lcw_c - LCW_NOM_C) \
            + 0.02 * math.sqrt(dt) * self.rng.standard_normal()
        lcw = (self.lcw_c + 0.35 * math.sin(2 * math.pi * self.t / 1200.0)
               + lcw_offset)
        return p, lcw

    @staticmethod
    def pack(p, lcw):
        return json.dumps({
            "lcw_c": round(float(lcw), 3),
            "p_mbar": {nm: round(float(p[k]), 3)
                       for k, (nm, _, _) in enumerate(CRYOMODULES)}})
