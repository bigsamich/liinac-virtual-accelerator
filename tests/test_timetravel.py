"""Phase 2: snapshot / restore / replay must be bit-exact."""
import os

import numpy as np

os.environ.setdefault("OMP_NUM_THREADS", "1")

from pip2va.sim import snapshot
from pip2va.sim.driver import SimDriver
from pip2va.sim.eventlog import EventLog


def _eq(a, b):
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        for k in ra:
            va, vb = ra[k], rb[k]
            if isinstance(va, np.ndarray):
                if not np.array_equal(va, vb):
                    return False
            elif va != vb:
                return False
    return True


def test_snapshot_restore_replay_bit_exact():
    """Run to A, snapshot; continue to B (record). Restore A, replay to B.
    The replayed stream must be byte-identical to the original tail."""
    d = SimDriver()
    d.run(50, {})                     # advance to pulse 50
    snap = snapshot.capture(d)
    original_tail = d.run(60, {})     # pulses 51..110 recorded
    # fresh driver, restored to the snapshot, replays the same 60 pulses
    d2 = SimDriver()
    snapshot.restore(d2, snap)
    replay_tail = d2.run(60, {})
    assert _eq(original_tail, replay_tail), "replay from snapshot is not exact"


def test_snapshot_isolated_from_parent():
    """A snapshot must not alias the driver — mutating the driver after capture
    must not change the snapshot (branch forks depend on this)."""
    d = SimDriver()
    d.run(10, {})
    snap = snapshot.capture(d)
    frozen = snap["setpoints"].copy()
    d.apply({"SSR1:C3:current_x": 5.0})
    d.run(5, {})
    assert snap["setpoints"] == frozen


def test_eventlog_roundtrip_and_replay():
    """The event log collapses to driver inputs and survives JSON round-trip."""
    log = EventLog()
    log.append(50, "setpoint", {"SSR1:C3:current_x": 0.4})
    log.append(100, "setpoint", {"SSR2:C4:current_y": -0.3})
    log2 = EventLog.from_json(log.to_json())
    assert log2.inputs_by_pulse() == {50: {"SSR1:C3:current_x": 0.4},
                                      100: {"SSR2:C4:current_y": -0.3}}
    # driving from the recovered event log reproduces a direct run
    a = SimDriver().run(120, log.inputs_by_pulse())
    b = SimDriver().run(120, log2.inputs_by_pulse())
    assert _eq(a, b)
