"""First-order device dynamics shared by the magnet and RF simulators:
slew-limited approach to setpoint, ripple/noise, slow drift, and a latched
trip state machine (trip clears only on explicit reset with the cause gone).
"""
from __future__ import annotations

import math

import numpy as np

from . import rng as _rng


class FirstOrderDevice:
    def __init__(self, setpoint: float, tau_s: float, ripple_frac: float,
                 drift_frac_per_hr: float = 0.0,
                 rng: np.random.Generator | None = None, eid: str | None = None):
        self.setpoint = setpoint
        self.value = setpoint          # actual (noiseless) internal state
        self.tau = max(tau_s, 1e-6)
        self.ripple = ripple_frac
        self.drift_rate = drift_frac_per_hr
        self.drift = 0.0
        self.tripped = False
        self.eid = eid                 # stable identity for deterministic noise
        self.rng = rng or np.random.default_rng()

    def step(self, dt: float, setpoint: float | None = None,
             pulse_id: int | None = None) -> float:
        """Advance dt seconds; returns the noisy readback.

        When ``pulse_id`` and ``eid`` are set, the ripple/drift draws are a pure
        function of ``(global_seed, pulse_id, eid, channel)`` — deterministic and
        CRN-shareable. Otherwise it falls back to the stateful ``self.rng``.
        """
        if setpoint is not None:
            self.setpoint = setpoint
        if self.tripped:
            return self.value  # dumped to zero by trip()
        self.value += (self.setpoint - self.value) * (1.0 - math.exp(-dt / self.tau))
        det = pulse_id is not None and self.eid is not None
        drift_rng = _rng.pulse_rng(pulse_id, self.eid, "drift") if det else self.rng
        ripple_rng = _rng.pulse_rng(pulse_id, self.eid, "ripple") if det else self.rng
        # slow thermal drift: bounded random walk (fraction of setpoint). The
        # accumulator `self.drift` is legitimate state (captured in snapshots);
        # only the increment is a deterministic per-pulse draw.
        if self.drift_rate:
            scale = abs(self.setpoint) or 1.0
            step = self.drift_rate / 3600.0 * dt * scale
            self.drift += drift_rng.normal(0.0, step) - self.drift * dt / 1800.0
        noise = ripple_rng.normal(0.0, self.ripple * (abs(self.value) or 1.0))
        return self.value + self.drift + noise

    def trip(self):
        """Latch the trip; output dumps to zero (fast discharge/RF off)."""
        self.tripped = True
        self.value = 0.0

    def try_reset(self) -> bool:
        """Clear the latch (caller must verify the cause is gone)."""
        self.tripped = False
        return True
