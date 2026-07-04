#!/usr/bin/env python3
"""Numerically match the lattice: tune every quad/solenoid strength so the
design envelope stays small and loss-free end to end, then bake the optimized
strengths back into pip2va/lattice/pip2_lattice.yaml.

Run after scripts/gen_lattice.py:
    python scripts/gen_lattice.py && python scripts/match_lattice.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pip2va.common.lattice import Lattice
from pip2va.physics.envelope import EnvelopeEngine

YAML_PATH = ROOT / "pip2va" / "lattice" / "pip2_lattice.yaml"

# rms size targets per section [m]
SIG_TARGET = {"LEBT": 4e-3, "MEBT": 1.8e-3, "HWR": 2.0e-3, "SSR1": 2.0e-3,
              "SSR2": 2.5e-3, "LB650": 2.5e-3, "HB650": 2.5e-3, "BTL": 3.0e-3}
ORDER = ["LEBT", "MEBT", "HWR", "SSR1", "SSR2", "LB650", "HB650", "BTL"]


def main():
    doc = yaml.safe_load(YAML_PATH.read_text())
    lat = Lattice(**doc)
    eng = EnvelopeEngine(lat)
    els = lat.elements
    sec_idx = {s: [i for i, e in enumerate(els) if e.section == s] for s in ORDER}

    overrides: dict[str, dict] = {}

    def run():
        return eng.run(overrides)

    def section_cost(sec: str, res) -> float:
        idx = sec_idx[sec]
        i0, i1 = idx[0], idx[-1]
        t_in = res.transmission[i0 - 1] if i0 > 0 else 1.0
        t_out = res.transmission[i1]
        lost = (t_in - t_out) / max(t_in, 1e-9)
        tgt = SIG_TARGET[sec]
        sig = np.maximum(res.sig_x[idx], res.sig_y[idx]) / tgt
        pen = float(np.mean(sig ** 4))
        # peek into next section: punish a blow-up handed downstream
        nxt = ORDER.index(sec) + 1
        peek = 0.0
        if nxt < len(ORDER):
            jdx = sec_idx[ORDER[nxt]][:12]
            tgt2 = SIG_TARGET[ORDER[nxt]]
            peek = float(np.mean(
                (np.maximum(res.sig_x[jdx], res.sig_y[jdx]) / tgt2) ** 4))
        return 1000.0 * lost + pen + 0.5 * peek

    for sec in ORDER:
        knobs = [e for i in sec_idx[sec]
                 if (e := els[i]).type in ("quad", "solenoid")]
        if not knobs:
            continue
        base = np.array([e.params["design_current"] for e in knobs])

        def cost(mult, _sec=sec, _knobs=knobs, _base=base):
            for e, m, b in zip(_knobs, mult, _base):
                overrides[e.name] = {"current": float(b * m)}
            return section_cost(_sec, run())

        x0 = np.ones(len(knobs))
        r0 = cost(x0)
        best = minimize(cost, x0, method="Powell",
                        bounds=[(0.25, 3.0)] * len(knobs),
                        options={"maxfev": 250 * len(knobs), "xtol": 1e-3,
                                 "ftol": 1e-4})
        r1 = cost(best.x)  # ensure overrides hold the best point
        res = run()
        i1 = sec_idx[sec][-1]
        print(f"{sec:6s}: cost {r0:10.3f} -> {r1:10.3f}   "
              f"T={res.transmission[i1]:.4f}  "
              f"sig_max={max(res.sig_x[sec_idx[sec]].max(), res.sig_y[sec_idx[sec]].max())*1e3:6.2f} mm")

    res = run()
    print(f"\nFINAL: T={res.transmission[-1]:.4f}  W={res.w[-1]:.1f} MeV  "
          f"max loss {res.loss_wpm.max():.3f} W/m")

    # bake optimized strengths into the YAML
    by_name = {e["name"]: e for e in doc["elements"]}
    # record design BLM levels — the MPS uses these as its threshold table
    blm_names = [e.name for e in lat.instruments("blm")]
    for j, nm in enumerate(blm_names):
        by_name[nm]["params"]["design_wpm"] = round(float(res.blm_wpm[j]), 4)
    for name, st in overrides.items():
        el = by_name[name]
        cur = st["current"]
        el["params"]["design_current"] = round(float(cur), 4)
        el["params"]["max_current"] = round(1.5 * abs(float(cur)), 2)
        if el["type"] == "quad":
            el["params"]["design_grad"] = round(
                cur * el["params"]["grad_per_amp"], 5)
        else:
            el["params"]["design_b"] = round(
                cur * el["params"]["field_per_amp"], 6)
    YAML_PATH.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    print(f"baked {len(overrides)} matched strengths into {YAML_PATH}")


if __name__ == "__main__":
    main()
