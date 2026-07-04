#!/usr/bin/env python3
"""Scan MEBT triplet strength/ratio + RFQ-exit Twiss for a loss-free front end."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np

from gen_lattice import build
from pip2va.common.lattice import Lattice
from pip2va.physics.envelope import EnvelopeEngine


def evaluate(gq, ratio, rfq_beta):
    doc = build(mebt_gq=float(gq), mebt_ratio=float(ratio),
                rfq_beta=float(rfq_beta))
    lat = Lattice(**doc)
    eng = EnvelopeEngine(lat)
    res = eng.run({}, current_ma=2.0)
    idx = [i for i, e in enumerate(lat.elements) if e.section == "MEBT"]
    t_mebt = res.transmission[idx[-1]]
    sig_max = max(max(res.sig_x[i] for i in idx), max(res.sig_y[i] for i in idx))
    return t_mebt, sig_max, res.transmission[-1]


best = None
for gq in np.arange(1.6, 7.01, 0.4):
    for ratio in np.arange(0.8, 2.21, 0.2):
        for rb in (0.6, 1.0, 1.5, 2.0, 3.0):
            t_mebt, sig_max, t_end = evaluate(gq, ratio, rb)
            score = (round(t_mebt, 3), round(t_end, 3), -sig_max)
            if best is None or score > best[0]:
                best = (score, gq, ratio, rb, t_mebt, sig_max, t_end)
                print(f"gq={gq:.1f} r={ratio:.1f} rb={rb:.1f} "
                      f"T_mebt={t_mebt:.4f} sig={sig_max*1e3:.1f}mm T_end={t_end:.4f}")

_, gq, ratio, rb, t_mebt, sig_max, t_end = best
print("\n-- refine --")
for dg in np.arange(-0.3, 0.31, 0.1):
    for dr in np.arange(-0.15, 0.16, 0.05):
        for rb2 in (rb * 0.8, rb, rb * 1.2):
            t_m, s_m, t_e = evaluate(gq + dg, ratio + dr, rb2)
            score = (round(t_m, 4), round(t_e, 4), -s_m)
            if score > best[0]:
                best = (score, gq + dg, ratio + dr, rb2, t_m, s_m, t_e)
                print(f"gq={gq+dg:.2f} r={ratio+dr:.2f} rb={rb2:.2f} "
                      f"T_mebt={t_m:.4f} sig={s_m*1e3:.1f}mm T_end={t_e:.4f}")

_, gq, ratio, rb, t_mebt, sig_max, t_end = best
print(f"\nBEST: gq={gq:.2f} ratio={ratio:.2f} rfq_beta={rb:.2f} "
      f"T_mebt={t_mebt:.4f} sig_max={sig_max*1e3:.2f}mm T_end={t_end:.4f}")
