"""Beam-loss models: Gaussian tail scraping + H- specific baselines."""
from __future__ import annotations

import math

# H- loss physics with verified parametrizations
# (docs/research/srf_beamline_report.md §7):
#   intrabeam stripping: Lebedev, sigma_max = 4e-19 m^2
#   residual gas: sigma = 1e-19/beta^2 cm^2 per H atom, H2 at PRESSURE_TORR
SIGMA_IBST_M2 = 4.0e-19
PRESSURE_TORR = 1e-8
E_CHARGE = 1.602e-19
F_BUNCH_HZ = 162.5e6


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


def hminus_baseline_frac_per_m(i_ma: float, beta: float, gamma: float,
                               sx: float, sy: float, sz: float,
                               thx: float = 1e-3, thy: float = 1e-3,
                               ths: float = 1e-3, ibst_scale: float = 1.0,
                               gas_scale: float = 1.0,
                               pressure_torr: float = PRESSURE_TORR) -> float:
    """Intrabeam stripping (Lebedev) + residual-gas stripping, frac/m.

    i_ma: in-pulse line current [mA]; th*: rms divergences x'/y' and dp/p.
    """
    # residual gas: sigma = 1e-19/beta^2 cm^2/atom, 2 atoms per H2 molecule,
    # n = 3.3e8 cm^-3 per 1e-8 Torr -> per metre factor 100
    gas = gas_scale * 100.0 * 3.3e8 * (pressure_torr / 1e-8) * 2.0 \
        * 1e-19 / max(beta * beta, 1e-6)
    # intrabeam stripping
    n_bunch = (i_ma * 1e-3) / (F_BUNCH_HZ * E_CHARGE)
    a, b, c = gamma * thx, gamma * thy, ths
    norm = math.sqrt(a * a + b * b + c * c)
    if norm < 1e-12:
        return gas
    form = 1.0 + 0.155 * ((a + b + c) / (math.sqrt(3.0) * norm) - 1.0)
    vol = max(sx * sy * sz, 1e-15)
    ibst = ibst_scale * (n_bunch * SIGMA_IBST_M2 * norm * form
                         / (8.0 * math.pi ** 2 * gamma ** 2 * vol))
    return gas + ibst
