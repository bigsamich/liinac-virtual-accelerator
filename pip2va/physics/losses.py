"""Beam-loss models: Gaussian tail scraping + H- specific baselines."""
from __future__ import annotations

import math

# H- baseline loss coefficients (tuned to reproduce the published scale:
# design machine sits well under the 0.1 W/m criterion, IBS dominant in the
# SC linac — see docs/research/pip2_machine_report.md §6). Only meaningful for
# the bunched beam downstream of the RFQ (the neutralized LEBT DC beam is
# handled by transport alone).
RESIDUAL_GAS_FRAC_PER_M = 5e-9      # fractional loss per metre
IBS_COEFF = 4.0e-17                  # scaled by I^2 / ((bg)^3 * sigma volume)


def tail_fraction(aperture: float, centroid: float, sigma: float) -> float:
    """Fraction of a 1D Gaussian (mean=centroid, std=sigma) outside +/-aperture."""
    if sigma <= 0.0:
        return 0.0 if abs(centroid) < aperture else 1.0
    sq2 = math.sqrt(2.0)
    f = 0.5 * (math.erfc((aperture - centroid) / (sq2 * sigma))
               + math.erfc((aperture + centroid) / (sq2 * sigma)))
    return min(1.0, f)


def scrape_fraction(ax: float, cx: float, sx: float,
                    ay: float, cy: float, sy: float) -> float:
    """Combined 2D loss fraction for an elliptical-ish aperture."""
    fx = tail_fraction(ax, cx, sx)
    fy = tail_fraction(ay, cy, sy)
    return fx + fy - fx * fy


def hminus_baseline_frac_per_m(i_ma: float, betagamma: float,
                               sx: float, sy: float, sz: float) -> float:
    """Intrabeam stripping + residual-gas stripping, fractional loss per metre."""
    vol = max(sx * sy * sz, 1e-12)
    ibs = IBS_COEFF * (i_ma ** 2) / (max(betagamma, 1e-3) ** 3 * vol)
    return RESIDUAL_GAS_FRAC_PER_M + ibs
