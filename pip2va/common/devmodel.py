"""First-order device dynamics shared by the magnet and RF simulators:
slew-limited approach to setpoint, ripple/noise, slow drift, and a latched
trip state machine (trip clears only on explicit reset with the cause gone).
"""
from __future__ import annotations

import math

import numpy as np


class FirstOrderDevice:
    def __init__(self, setpoint: float, tau_s: float, ripple_frac: float,
                 drift_frac_per_hr: float = 0.0, rng: np.random.Generator | None = None):
        self.setpoint = setpoint
        self.value = setpoint          # actual (noiseless) internal state
        self.tau = max(tau_s, 1e-6)
        self.ripple = ripple_frac
        self.drift_rate = drift_frac_per_hr
        self.drift = 0.0
        self.tripped = False
        self.rng = rng or np.random.default_rng()

    def step(self, dt: float, setpoint: float | None = None) -> float:
        """Advance dt seconds; returns the noisy readback."""
        if setpoint is not None:
            self.setpoint = setpoint
        if self.tripped:
            return self.value  # dumped to zero by trip()
        self.value += (self.setpoint - self.value) * (1.0 - math.exp(-dt / self.tau))
        # slow thermal drift: bounded random walk (fraction of setpoint)
        if self.drift_rate:
            scale = abs(self.setpoint) or 1.0
            step = self.drift_rate / 3600.0 * dt * scale
            self.drift += self.rng.normal(0.0, step) - self.drift * dt / 1800.0
        noise = self.rng.normal(0.0, self.ripple * (abs(self.value) or 1.0))
        return self.value + self.drift + noise

    def trip(self):
        """Latch the trip; output dumps to zero (fast discharge/RF off)."""
        self.tripped = True
        self.value = 0.0

    def try_reset(self) -> bool:
        """Clear the latch (caller must verify the cause is gone)."""
        self.tripped = False
        return True
