"""Phase 3 + 4: commit-horizon input and the what-if branch engine."""
import os

import numpy as np

os.environ.setdefault("OMP_NUM_THREADS", "1")

from pip2va.sim import branch, snapshot
from pip2va.sim.driver import SimDriver
from pip2va.sim.input import InputInjector


def _eq(a, b):
    for ra, rb in zip(a, b):
        for k in ra:
            va, vb = ra[k], rb[k]
            if isinstance(va, np.ndarray):
                if not np.array_equal(va, vb):
                    return False
            elif va != vb:
                return False
    return len(a) == len(b)


# ---- Phase 3: commit-horizon input -----------------------------------------

def test_commit_horizon_deterministic_and_replayable():
    """Two runs with the same submit schedule are identical; and replaying the
    resulting event log reproduces the run."""
    def scripted():
        d = SimDriver()
        inj = InputInjector(d, horizon=2)
        out = []
        for p in range(60):
            if d.pulse_id == 20:
                inj.submit({"SSR1:C3:current_x": 0.6})
            out.append(inj.step())
        return out, inj.log
    a, log_a = scripted()
    b, _ = scripted()
    assert _eq(a, b)
    # replay from the recorded event log (inputs land at their committed pulse)
    replay = SimDriver().run(60, log_a.inputs_by_pulse())
    assert _eq(a, replay)


# ---- Phase 4: branch engine ------------------------------------------------

def _base():
    d = SimDriver()
    d.run(30, {})
    return snapshot.capture(d)


def test_crn_same_delta_identical():
    """Common Random Numbers: two branches with the SAME delta are identical."""
    base = _base()
    res = branch.fork(base, [{"SSR1:C3:current_x": 0.5},
                             {"SSR1:C3:current_x": 0.5}], 20, keep_stream=True)
    assert _eq(res[0].stream, res[1].stream)


def test_branch_does_not_mutate_parent():
    base = _base()
    frozen = dict(base["setpoints"])
    branch.fork(base, [{"SSR1:C3:current_x": 9.0}], 10)
    assert base["setpoints"] == frozen


def test_parallel_equals_serial():
    base = _base()
    deltas = [{"SSR1:C3:current_x": v} for v in (-0.4, 0.0, 0.4, 0.8)]
    serial = branch.fork(base, deltas, 15, workers=1)
    parallel = branch.fork(base, deltas, 15, workers=4)
    for s, p in zip(serial, parallel):
        assert s.metrics == p.metrics


def test_branch_delta_changes_outcome():
    """A real setpoint delta must move the metrics (branches aren't no-ops)."""
    base = _base()
    res = branch.fork(base, [{}, {"SSR1:C3:current_x": 1.0}], 15)
    assert res[0].metrics["orbit_rms_mm"] != res[1].metrics["orbit_rms_mm"]
