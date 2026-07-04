#!/usr/bin/env python3
"""Generate pip2va/lattice/errors.yaml — the machine's static imperfections.

Seeded random misalignments and diagnostic systematics at published survey
scales (SC solenoid packages 0.2 mm rms, warm quads 0.15 mm; BPM electrical
offsets 0.1 mm rms, scale errors 2% rms). Regenerate with a new seed for a
different "as-built" machine.

Run:  python scripts/gen_errors.py [seed]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pip2va.common.lattice import load_lattice  # noqa: E402

OUT = ROOT / "pip2va" / "lattice" / "errors.yaml"

MISALIGN_RMS = {"solenoid": 0.06e-3, "quad": 0.05e-3}  # m; orbit amplification in
# the solenoid channel is ~x30, so survey-scale errors are applied pre-steered
# ("after first-pass commissioning") to boot the machine ugly but alive
BPM_OFFSET_RMS = 0.10e-3    # m electrical-vs-magnetic centre
BPM_SCALE_RMS = 0.02        # fractional


def trunc_normal(rng, sigma, n=1, cut=2.5):
    v = rng.normal(0.0, sigma, n)
    return np.clip(v, -cut * sigma, cut * sigma)


def main(seed: int = 20260704):
    rng = np.random.default_rng(seed)
    lat = load_lattice()
    errors: dict = {}
    for el in lat.elements:
        if el.type in MISALIGN_RMS:
            s = MISALIGN_RMS[el.type]
            errors[el.name] = {
                "dx": round(float(trunc_normal(rng, s)[0]), 8),
                "dy": round(float(trunc_normal(rng, s)[0]), 8),
            }
        elif el.type == "bpm":
            errors[el.name] = {
                "offset_x": round(float(trunc_normal(rng, BPM_OFFSET_RMS)[0]), 8),
                "offset_y": round(float(trunc_normal(rng, BPM_OFFSET_RMS)[0]), 8),
                "scale": round(float(1.0 + trunc_normal(rng, BPM_SCALE_RMS)[0]), 6),
            }
    OUT.write_text(yaml.safe_dump({"seed": seed, "errors": errors},
                                  sort_keys=False))
    n_mag = sum(1 for v in errors.values() if "dx" in v)
    n_bpm = sum(1 for v in errors.values() if "offset_x" in v)
    print(f"wrote {OUT} — {n_mag} misaligned magnets, {n_bpm} BPM systematics "
          f"(seed {seed})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20260704)
