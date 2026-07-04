"""Relativistic kinematics for the H- beam. Energies in MeV, lengths in m."""
from __future__ import annotations

import math

M_MEV = 939.294          # H- rest mass
C_LIGHT = 299_792_458.0  # m/s


def beta_gamma(w_mev: float) -> tuple[float, float]:
    gamma = 1.0 + w_mev / M_MEV
    beta = math.sqrt(1.0 - 1.0 / (gamma * gamma))
    return beta, gamma


def momentum(w_mev: float) -> float:
    """p [MeV/c]."""
    return math.sqrt(w_mev * (w_mev + 2.0 * M_MEV))


def brho(w_mev: float) -> float:
    """Magnetic rigidity [T*m] for unit charge."""
    return momentum(w_mev) / 299.792458
