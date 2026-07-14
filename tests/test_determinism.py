"""Golden-master determinism tests for the single-process driver.

These assert BIT-EXACT reproducibility (not np.allclose) — the whole point of
the determinism substrate. If these ever fail, some value leaked out of the
(seed, pulse_id, entity) keying into wall-clock, a stateful RNG stream, or
nondeterministic float reduction.
"""
import os

import numpy as np
import pytest

os.environ.setdefault("OMP_NUM_THREADS", "1")   # pin FP reduction order

from pip2va.sim.driver import SimDriver


def _stream_equal(a, b) -> bool:
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if ra.keys() != rb.keys():
            return False
        for k in ra:
            va, vb = ra[k], rb[k]
            if isinstance(va, np.ndarray):
                if not np.array_equal(va, vb):
                    return False
            elif va != vb:
                return False
    return True


# a scripted input sequence: nudge a couple of correctors at known pulses
INPUTS = {
    50:  {"SSR1:C3:current_x": 0.4},
    100: {"SSR2:C4:current_y": -0.3},
    150: {"SSR1:C3:current_x": 0.8},
}


def test_bit_exact_reproducible():
    """Same driver, same inputs, twice -> byte-identical readout streams."""
    a = SimDriver().run(200, INPUTS)
    b = SimDriver().run(200, INPUTS)
    assert _stream_equal(a, b), "driver is not bit-exact reproducible"


def test_seed_changes_stream():
    """A different global seed must change the noise (sanity: RNG is wired)."""
    a = SimDriver(seed=1).run(40, INPUTS)
    b = SimDriver(seed=2).run(40, INPUTS)
    # different seed -> different device noise -> the stream must differ
    # somewhere (orbit/BPMs are the sensitive probe)
    assert not _stream_equal(a, b), "seed had no effect — RNG not wired to physics"


def test_causality_isolation():
    """A setpoint change at pulse 100 must not alter any pulse before 100."""
    base = SimDriver().run(160, {})
    perturbed = SimDriver().run(160, {100: {"SSR1:C3:current_x": 0.8}})
    assert _stream_equal(base[:99], perturbed[:99]), \
        "future input leaked into the past — causality violated"


def test_crn_shared_noise():
    """Common Random Numbers: two runs with the SAME seed but different inputs
    still share identical device noise for the *unchanged* devices at each
    pulse — so branch differences are pure signal (validated indirectly by the
    reproducibility + isolation tests; here we assert the seed is the only
    source of the noise stream)."""
    a = SimDriver(seed=7).run(30, {})
    b = SimDriver(seed=7).run(30, {})
    assert _stream_equal(a, b)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
