"""Booster injection performance — the machine's figure of merit.

Charge-exchange (H- foil) injection at 800 MeV, painted over ~285 turns.
This model scores each linac pulse on how well it would inject into the
Booster, from the *real* delivered beam (normalised emittance and momentum
spread from the envelope, orbit at the foil) plus the injection knobs.

The physics that sets the optimum:
  - RF bucket capture: the momentum tails outside the Booster adiabatic-capture
    acceptance (~+/-0.3%) are lost; the chopper notch must clear the extraction kicker.
  - Space-charge tune shift (Laslett): the design driver. Painting spreads
    the beam to a larger emittance to keep the incoherent tune shift ΔQ_sc
    below the resonance limit (~0.35). Too-dense paint -> ΔQ over limit ->
    loss; too-diffuse -> overflows the Booster acceptance.
  - Foil hits: protons re-traverse the foil while the injection bump still
    overlaps it. Each traversal adds emittance by multiple Coulomb
    scattering and heats the foil. Fast bump decay + adequate bump = fewer
    hits.

All inputs are knobs or real beam quantities, so it is fully study-able.
"""
from __future__ import annotations

import math

TURNS = 285
BUCKET_DPP = 0.003          # Booster adiabatic-capture momentum acceptance
R_P = 1.5347e-18            # classical proton radius [m]
GAMMA = 1.0 + 800.0 / 938.272   # 800 MeV kinetic
BETA = math.sqrt(1.0 - 1.0 / GAMMA ** 2)
BG2 = BETA * GAMMA ** 2
DQ_LIMIT = 0.35            # incoherent space-charge tune-shift limit
ACCEPT_UM = 20.0           # Booster transverse acceptance (norm rms class)
# carbon stripping foil ~600 µg/cm^2; Highland multiple-scattering rms angle
_X_OVER_X0 = 600e-6 / 42.7
_THETA_MS = (13.6 / (BETA * 800.0 + 938.272 * (GAMMA - 1))) * \
    math.sqrt(_X_OVER_X0) * (1 + 0.038 * math.log(_X_OVER_X0))   # rad/traversal
BETA_FOIL = 10.0           # Booster beta at the foil [m]
DEPS_FOIL = 0.5 * BETA_FOIL * _THETA_MS ** 2 * 1e6   # µm norm growth per hit


def score(i_out_ma: float, eps_x_um: float, eps_y_um: float,
          sig_x_mm: float, sig_y_mm: float, cx_mm: float, cy_mm: float,
          dpp_rms: float, bump0_mm: float, decay_turns: float,
          notch_ok: bool, duty: float) -> dict:
    """Injection performance for one pulse. Emittances are normalised rms
    [µm = mm·mrad]; sizes [mm]; dpp_rms dimensionless."""
    # unphysical beam (tripped / diverged envelope): no meaningful score
    if not all(math.isfinite(x) for x in
               (eps_x_um, eps_y_um, sig_x_mm, sig_y_mm, dpp_rms, i_out_ma)) \
            or max(eps_x_um, eps_y_um) > 500.0 or i_out_ma <= 0.0:
        return {"protons_per_pulse": 0.0, "capture_eff": 0.0,
                "eps_inj_um": 0.0, "eps_paint_um": 0.0, "dq_sc": 0.0,
                "sc_loss_frac": 0.0, "accept_frac": 0.0, "foil_hits": 0.0,
                "score": 0.0}

    # ---- protons delivered to the foil in one 0.55 ms pulse
    protons_in = (i_out_ma * 1e-3 * 0.55e-3) / 1.602e-19

    # ---- RF bucket capture (longitudinal) + kicker-notch
    capture = math.erf(BUCKET_DPP / max(dpp_rms, 1e-6) / math.sqrt(2)) \
        * (1.0 if notch_ok else 0.90)

    # ---- painting: spread the injected beam to a larger emittance. The bump
    # sweeps the closed orbit across the injected beam; painted emittance
    # grows with (bump amplitude / beam size)^2 above the injected floor.
    sig = max((sig_x_mm + sig_y_mm) / 2.0, 0.2)
    eps_inj = max((eps_x_um + eps_y_um) / 2.0, 0.05)
    orbit_err = math.hypot(cx_mm, cy_mm)
    eps_paint = eps_inj * (1.0 + 0.6 * (bump0_mm / (2.0 * sig)) ** 2)

    # ---- foil hits from the painting geometry, then scattering growth
    overlap = decay_turns * min(1.0, 2.2 * sig / max(bump0_mm, 0.5))
    foil_hits = (1.0 + 0.5 * overlap) * (1.0 + 0.10 * orbit_err)
    eps_paint = eps_paint * (1.0 + 0.05 * orbit_err) + foil_hits * DEPS_FOIL

    # ---- space-charge tune shift (Laslett, incoherent) over the painted
    # circulating intensity; bunching factor from the chopper duty.
    n_ring = protons_in                      # painted, one pulse
    bf = max(duty, 0.05)                     # bunching factor ~ duty
    eps_m = eps_paint * 1e-6                  # µm -> m·rad (normalised)
    dq_sc = (n_ring * R_P) / (4 * math.pi * eps_m * BG2 * bf)

    # ---- loss channels
    #   space charge: resonance loss when |ΔQ| exceeds the limit
    sc_frac = 1.0 - min(1.0, max(0.0, (dq_sc / DQ_LIMIT - 1.0)) * 0.5)
    #   acceptance: painted emittance must fit the Booster acceptance
    acc_frac = min(1.0, (ACCEPT_UM / max(eps_paint, 1e-3)) ** 0.5)

    protons_stacked = protons_in * capture * sc_frac * acc_frac

    # ---- composite score (0-100): stacked vs a 2 mA / matched ideal,
    # penalised by the foil-hit budget (heating / scattering)
    ideal = 2.0e-3 * 0.55e-3 / 1.602e-19 * (duty / 0.4)
    s100 = 100.0 * (protons_stacked / max(ideal, 1.0)) \
        * min(1.0, 6.0 / max(foil_hits, 1.0)) ** 0.3

    return {"protons_per_pulse": protons_stacked,
            "capture_eff": capture,
            "eps_inj_um": eps_inj,
            "eps_paint_um": eps_paint,
            "dq_sc": dq_sc,
            "sc_loss_frac": 1.0 - sc_frac,
            "accept_frac": acc_frac,
            "foil_hits": foil_hits,
            "score": min(s100, 100.0)}
