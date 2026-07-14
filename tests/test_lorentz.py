"""Phase 7: Lorentz (magnetic) stripping of H- in the BTL dipoles."""
import math

from pip2va.physics import losses

# 800 MeV H- kinematics
M = 939.294
GAMMA = 1.0 + 800.0 / M
BETA = math.sqrt(1.0 - 1.0 / GAMMA ** 2)


def _f(b):
    return losses.lorentz_strip_frac_per_m(b, BETA, GAMMA)


def test_negligible_at_design_field():
    """At the design 0.24 T the loss is vanishing (below activation concern)."""
    assert _f(0.24) < 1e-9


def test_monotonic_and_explodes_above_knee():
    """Loss rises monotonically and sharply (exponentially) with B."""
    vals = [_f(b) for b in (0.24, 0.28, 0.32, 0.40)]
    assert all(b > a for a, b in zip(vals, vals[1:]))     # strictly increasing
    assert vals[-1] > 1e5 * vals[0]                       # exponential blow-up
    assert _f(0.40) > 1e-7                                # genuinely significant


def test_zero_field_zero_loss():
    assert _f(0.0) == 0.0


def test_scale_knob():
    assert losses.lorentz_strip_frac_per_m(0.30, BETA, GAMMA, scale=2.0) == \
        2.0 * losses.lorentz_strip_frac_per_m(0.30, BETA, GAMMA, scale=1.0)


def test_envelope_integrates_it():
    """Cranking lorentz_scale must raise total BTL loss without crashing."""
    import numpy as np
    from pip2va.physics.envelope import EnvelopeEngine
    from pip2va.common.lattice import load_lattice
    eng = EnvelopeEngine(load_lattice())
    base = eng.run({}, beam_on=True)
    eng.phys = {"lorentz_scale": 1e6}       # absurd scale -> visible arc loss
    hot = eng.run({}, beam_on=True)
    assert np.sum(hot.blm_wpm) >= np.sum(base.blm_wpm)
