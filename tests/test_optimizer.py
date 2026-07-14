"""Phase 6: optimizer + injection auto-tune on the branch engine."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

from pip2va.analysis import optimizer as opt
from pip2va.sim import snapshot
from pip2va.sim.driver import SimDriver


def _base(bump=8.0, decay=12.0):
    d = SimDriver()
    d.apply({"inj:bump0_mm": bump, "inj:decay_turns": decay})
    d.run(20, {})
    return snapshot.capture(d)


def test_injection_autotune_improves_and_is_deterministic():
    """From a deliberately poor painting config, the optimizer raises the
    injection score, reproducibly."""
    base = _base(bump=0.5, decay=280.0)      # bad starting point
    r1 = opt.autotune_injection(base, n_pulses=6, iters=20)
    r2 = opt.autotune_injection(base, n_pulses=6, iters=20)
    assert r1.score >= r1.baseline           # never worse than the start
    assert r1.score > r1.baseline            # actually improved
    assert r1.best == r2.best                # deterministic
    assert r1.score == r2.score


def test_sensitivity_signal():
    """CRN sensitivity returns finite d(score)/d(knob) for the painting knobs."""
    base = _base()
    knobs = [opt.Knob("inj:bump0_mm", 0.5, 25.0, 8.0, 3.0),
             opt.Knob("inj:decay_turns", 5.0, 285.0, 12.0, 20.0)]
    jac = opt.sensitivity(base, knobs, "inj_score_mean", n_pulses=6)
    assert set(jac) == {"inj:bump0_mm", "inj:decay_turns"}
    assert all(isinstance(v, float) for v in jac.values())
