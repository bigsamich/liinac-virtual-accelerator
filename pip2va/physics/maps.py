"""6x6 linear transfer maps in coordinates (x, x', y, y', z, delta=dp/p).

Conventions: z > 0 means the particle arrives EARLY (ahead of the synchronous
particle); a drift couples z' = delta / gamma^2; an off-crest gap at phi < 0
then gives d(delta)/dz < 0, closing a stable synchrotron oscillation.
"""
from __future__ import annotations

import math

import numpy as np

from .kinematics import M_MEV, beta_gamma


def identity() -> np.ndarray:
    return np.eye(6)


def drift(L: float, beta: float, gamma: float) -> np.ndarray:
    m = np.eye(6)
    m[0, 1] = L
    m[2, 3] = L
    m[4, 5] = L / (gamma * gamma)
    return m


def quad(L: float, k1: float, beta: float, gamma: float) -> np.ndarray:
    """Thick quadrupole; k1 > 0 focuses in x. k1 in 1/m^2."""
    if abs(k1) < 1e-12:
        return drift(L, beta, gamma)
    m = np.eye(6)
    k = math.sqrt(abs(k1))
    c, s = math.cos(k * L), math.sin(k * L)
    ch, sh = math.cosh(k * L), math.sinh(k * L)
    foc = np.array([[c, s / k], [-k * s, c]])
    defoc = np.array([[ch, sh / k], [k * sh, ch]])
    if k1 > 0:
        m[0:2, 0:2], m[2:4, 2:4] = foc, defoc
    else:
        m[0:2, 0:2], m[2:4, 2:4] = defoc, foc
    m[4, 5] = L / (gamma * gamma)
    return m


def solenoid(L: float, B: float, brho: float, beta: float, gamma: float) -> np.ndarray:
    """Thick solenoid (coupled x-y), Larmor wavenumber k = B / (2 Brho)."""
    if abs(B) < 1e-12:
        return drift(L, beta, gamma)
    k = B / (2.0 * brho)
    C, S = math.cos(k * L), math.sin(k * L)
    m = np.eye(6)
    m[0:4, 0:4] = np.array([
        [C * C,      S * C / k,  S * C,      S * S / k],
        [-k * S * C, C * C,      -k * S * S, S * C],
        [-S * C,     -S * S / k, C * C,      S * C / k],
        [k * S * S,  -S * C,     -k * S * C, C * C],
    ])
    m[4, 5] = L / (gamma * gamma)
    return m


def rfgap_kick(w_in: float, v_mv: float, phi_deg: float, freq_mhz: float
               ) -> tuple[float, np.ndarray, float]:
    """Thin accelerating gap (Panofsky).

    Energy gain dW = q V cos(phi); transverse RF defocusing
    k_t = -pi V sin(phi) / (m beta^2 gamma^3 lambda)  [1/m], applied as a thin
    lens in both planes; linearized longitudinal focusing in (z, delta).

    Returns (W_out, M6, k_t) with M6 evaluated at the mid-gap energy.
    """
    phi = math.radians(phi_deg)
    w_out = w_in + v_mv * math.cos(phi)
    w_mid = 0.5 * (w_in + w_out)
    beta, gamma = beta_gamma(w_mid)
    lam = 299.792458 / freq_mhz  # wavelength in m

    m = np.eye(6)
    k_t = -math.pi * v_mv * math.sin(phi) / (M_MEV * beta**2 * gamma**3 * lam)
    m[1, 0] = k_t
    m[3, 2] = k_t
    # longitudinal: particle at z (early, sees phi - kz*z) ->
    # d(dW) = +V sin(phi) kz z ; delta kick = d(dW)/(m beta^2 gamma)
    kz = 2.0 * math.pi / (beta * lam)
    m54 = v_mv * math.sin(phi) * kz / (M_MEV * beta**2 * gamma)
    # cap per-gap synchrotron focusing at ~60 deg per metre-cell: stands in
    # for the adiabatic phase/voltage ramp real designs use — without it the
    # longitudinal plane over-focuses (>180 deg/period) and debunches
    cap = 1.1 * gamma * gamma
    m[5, 4] = max(-cap, min(cap, m54))
    # adiabatic damping of transverse angles from acceleration
    bg_ratio = (beta * gamma) / _bg(w_out)
    m[1, 1] *= bg_ratio
    m[3, 3] *= bg_ratio
    return w_out, m, k_t


def _bg(w: float) -> float:
    b, g = beta_gamma(w)
    return b * g


def sbend(L: float, angle_rad: float, beta: float, gamma: float,
          disp_scale: float = 1.0) -> np.ndarray:
    """Sector dipole with dispersion (x-plane weak focusing, R16/R51/R56)."""
    if abs(angle_rad) < 1e-9:
        return drift(L, beta, gamma)
    rho = L / angle_rad
    h = 1.0 / rho
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    m = np.eye(6)
    m[0, 0], m[0, 1], m[0, 5] = c, rho * s, disp_scale * rho * (1 - c)
    m[1, 0], m[1, 1], m[1, 5] = -h * s, c, disp_scale * s
    m[2, 3] = L
    m[4, 0], m[4, 1] = -disp_scale * s, -disp_scale * rho * (1 - c)
    m[4, 5] = L / (gamma * gamma) - (L - rho * s)
    return m


def corrector_kick(angle_x: float, angle_y: float) -> np.ndarray:
    """Additive centroid kick vector for a dipole corrector."""
    v = np.zeros(6)
    v[1] = angle_x
    v[3] = angle_y
    return v
