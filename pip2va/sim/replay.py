"""Record-replay + stream diff — cashing in determinism for debugging.

A run is a pure function of ``(snapshot, event log, seed)``, so any window is
exactly reconstructable and two runs can be diffed down to the precise pulse and
field where they first diverge. That turns "flaky, can't reproduce" into
"reproduce it byte-for-byte and point at the first differing value" — the
foundation for causal debugging.
"""
from __future__ import annotations

import numpy as np

from . import snapshot as _snap
from .driver import SimDriver
from .eventlog import EventLog


def replay(snapshot_dict: dict, log: EventLog, n_pulses: int,
           seed: int | None = None) -> list[dict]:
    """Reconstruct ``n_pulses`` from a snapshot + its event log, bit-exactly."""
    d = SimDriver(seed=seed)
    _snap.restore(d, snapshot_dict)
    return d.run(n_pulses, log.inputs_by_pulse())


def first_divergence(a: list[dict], b: list[dict]) -> dict | None:
    """First point where two readout streams differ -> {pulse_index, field, ...}
    or None if identical. This is the causal-debug entry point: given a bad
    run vs a good one, it localizes *where* they split."""
    for i, (ra, rb) in enumerate(zip(a, b)):
        for k in ra:
            va, vb = ra[k], rb[k]
            if isinstance(va, np.ndarray):
                if not np.array_equal(va, vb):
                    idx = int(np.argmax(va != vb)) if va.shape == vb.shape else -1
                    return {"pulse_index": i, "pulse_id": ra.get("pulse_id"),
                            "field": k, "elem_index": idx}
            elif va != vb:
                return {"pulse_index": i, "pulse_id": ra.get("pulse_id"),
                        "field": k, "a": va, "b": vb}
    if len(a) != len(b):
        return {"pulse_index": min(len(a), len(b)), "field": "<length>",
                "a": len(a), "b": len(b)}
    return None
