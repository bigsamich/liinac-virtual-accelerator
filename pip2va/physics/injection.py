"""Booster injection performance — the machine's actual figure of merit.

Charge-exchange injection: each 0.55 ms linac pulse paints ~285 Booster
turns through a stripping foil, with ORBUMP magnets collapsing the closed
orbit across the foil to spread the painted emittance and minimize
re-traversals (foil hits cause scattering, emittance growth, and foil
heating). What matters:

  - protons per pulse actually stacked (delivered charge x stripping x
    bucket capture),
  - bucket capture: dp/p must fit the Booster RF bucket (~+/-0.2%), and
    the chopper pattern must respect the extraction-kicker notch,
  - painted emittance vs target (Booster acceptance ~ 12 mm.mrad class),
  - average foil hits per proton (heating / scattering budget, ~<6).

Scored per pulse from beam truth + settings. All inputs are knobs, so
painting is study-able and optimizable.
"""
from __future__ import annotations

import math

TURNS = 285
FOIL_STRIP_EFF = 0.98          # H- -> p conversion per traversal
BUCKET_DPP = 0.002             # Booster RF bucket half-height
EPS_TARGET_UM = 12.0           # painted-emittance target (norm, rms class)


def score(i_out_ma: float, sig_x_mm: float, sig_y_mm: float,
          cx_mm: float, cy_mm: float, dpp_rms: float,
          bump0_mm: float, decay_turns: float,
          notch_ok: bool, duty: float) -> dict:
    """Injection performance for one pulse."""
    # protons delivered to the foil in 0.55 ms
    q = i_out_ma * 1e-3 * 0.55e-3            # coulombs
    protons_in = q / 1.602e-19

    # bucket capture: momentum tails outside the bucket are lost at
    # Booster capture; a missing/kicked notch costs the kicker-gap beam
    frac_dpp = math.erf(BUCKET_DPP / max(dpp_rms, 1e-6) / math.sqrt(2))
    eff = FOIL_STRIP_EFF * frac_dpp * (1.0 if notch_ok else 0.90)

    # painting: the bump collapses bump0 -> 0 over decay_turns; painted
    # emittance ~ (bump amplitude relative to beam size)^2 term + beam
    # emittance floor. Too-small bump = hot spot (foil hits), too-large =
    # blows the acceptance.
    sig = max((sig_x_mm + sig_y_mm) / 2.0, 0.3)
    eps_paint = 2.5 + 0.09 * (bump0_mm ** 2) / sig
    # foil hits: proton re-traverses the foil while the bump still
    # overlaps it; faster decay + larger bump = fewer hits
    overlap_turns = decay_turns * min(1.0, 2.2 * sig / max(bump0_mm, 0.5))
    foil_hits = 1.0 + overlap_turns * 0.5
    # orbit error at the foil directly biases painting + hits
    orbit_err = math.hypot(cx_mm, cy_mm)
    eps_paint *= 1.0 + 0.06 * orbit_err
    foil_hits *= 1.0 + 0.10 * orbit_err

    acc_frac = min(1.0, EPS_TARGET_UM / max(eps_paint, 1e-3)) ** 0.5
    protons_stacked = protons_in * eff * min(acc_frac + 0.5, 1.0)
    # composite score (0-100): stacked charge vs ideal, penalized by hits
    ideal = 2.0e-3 * 0.55e-3 / 1.602e-19 * duty / 0.4
    s100 = 100.0 * (protons_stacked / max(ideal, 1)) \
        * min(1.0, 6.0 / max(foil_hits, 1.0)) ** 0.3
    return {"protons_per_pulse": protons_stacked,
            "capture_eff": eff,
            "eps_paint_um": eps_paint,
            "foil_hits": foil_hits,
            "score": min(s100, 100.0)}
