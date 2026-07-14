"""Frame-boundary state snapshots for the deterministic driver.

A snapshot is the full mutable state at a pulse boundary: pulse_id, setpoints,
and every device's internal state (slew value, drift accumulator, setpoint,
trip latch). Because the driver's randomness is a pure function of
``(seed, pulse_id, eid)``, ``restore(snap)`` + replay reproduces the future
bit-for-bit — that's what makes rewind, branching, and record-replay exact.

Snapshots are plain dicts (JSON/msgpack-serializable), so they persist and ship
across processes for the branch engine.
"""
from __future__ import annotations

import copy


def capture(driver) -> dict:
    """Immutable snapshot of the driver's state at the current frame."""
    return {
        "pulse_id": driver.pulse_id,
        "global_seed": driver.settings.global_seed,
        "src_current_ma": driver.src_current_ma,
        "setpoints": dict(driver.setpoints),
        "devices": {
            dev.eid: {
                "value": dev.value, "drift": dev.drift,
                "setpoint": dev.setpoint, "tripped": dev.tripped,
            }
            for _el, _f, dev in driver.devices
        },
    }


def restore(driver, snap: dict) -> None:
    """Restore a driver to a captured snapshot (in place)."""
    driver.pulse_id = snap["pulse_id"]
    driver.src_current_ma = snap["src_current_ma"]
    driver.setpoints = dict(snap["setpoints"])
    driver.settings = driver.settings.model_copy(
        update={"global_seed": snap["global_seed"]})
    dstate = snap["devices"]
    for _el, _f, dev in driver.devices:
        s = dstate.get(dev.eid)
        if s is None:
            continue
        dev.value = s["value"]
        dev.drift = s["drift"]
        dev.setpoint = s["setpoint"]
        dev.tripped = s["tripped"]


def clone(snap: dict) -> dict:
    """Deep copy — a fork's starting point must not alias the parent's."""
    return copy.deepcopy(snap)
