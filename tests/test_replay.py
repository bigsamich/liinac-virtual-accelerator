"""Phase 8: record-replay + divergence localization."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

from pip2va.sim import replay, snapshot
from pip2va.sim.driver import SimDriver
from pip2va.sim.eventlog import EventLog


def test_replay_matches_and_diff_is_none():
    d = SimDriver()
    d.run(20, {})
    snap = snapshot.capture(d)
    log = EventLog()
    log.append(d.pulse_id + 5, "setpoint", {"SSR1:C3:current_x": 0.5})
    original = SimDriver()
    snapshot.restore(original, snap)
    ref = original.run(30, log.inputs_by_pulse())
    rep = replay.replay(snap, log, 30)
    assert replay.first_divergence(ref, rep) is None


def test_diff_localizes_divergence():
    """Two runs that differ from pulse-index 10 onward are localized there."""
    a = SimDriver().run(30, {})
    b = SimDriver().run(30, {11: {"SSR1:C3:current_x": 1.0}})
    d = replay.first_divergence(a, b)
    assert d is not None
    assert d["pulse_index"] >= 10          # unchanged before the input lands
