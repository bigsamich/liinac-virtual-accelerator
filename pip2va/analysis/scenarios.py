"""Training scenarios: scripted fault campaigns with recovery scoring."""
from __future__ import annotations

import time

SCENARIOS = {
    "Cavity trip in the spokes": {
        "desc": "An SSR2 cavity quenches. Diagnose which one, reset it, and "
                "recover the beam permit.",
        "faults": [("rf", "SSR2:CAV17", "trip", 1, 0)],
        "par": 60.0,
    },
    "Stuck tuner (detune)": {
        "desc": "A cavity tuner walks 300 Hz off resonance. Find it from the "
                "RF page detuning column before losses trip the machine.",
        "faults": [("rf", "LB650:CAV22", "detune", 300.0, 0)],
        "par": 90.0,
    },
    "Drifting solenoid supply": {
        "desc": "An HWR solenoid supply drifts at 6 A/min. Watch the orbit "
                "and losses walk; catch and correct it.",
        "faults": [("magnet", "HWR:SOL4", "drift", 6.0, 120)],
        "par": 120.0,
    },
    "Double fault": {
        "desc": "A cavity trips WHILE a corrector drifts. Untangle which "
                "fault explains which symptom.",
        "faults": [("rf", "SSR1:CAV11", "trip", 1, 0),
                   ("magnet", "SSR2:C14", "drift", 4.0, 90)],
        "par": 180.0,
    },
}


def start(r, hub_inject, name: str) -> None:
    sc = SCENARIOS[name]
    for cls, dev, typ, mag, ttl in sc["faults"]:
        hub_inject(cls, dev, typ, mag, ttl)
    r.hset("state:training", mapping={
        "scenario": name, "t0": time.time(), "active": 1, "score": -1.0})


def check(r) -> dict:
    st = {k.decode(): v.decode() for k, v in r.hgetall("state:training").items()}
    if not st or st.get("active") != "1":
        return st
    beam = {k.decode(): v.decode() for k, v in r.hgetall("state:beam").items()}
    permit = r.get("state:mps.permit") in (b"1", "1")
    faults = list(r.scan_iter("fault:*"))
    healthy = (permit and not faults
               and float(beam.get("transmission", 0)) > 0.99)
    if healthy:
        elapsed = time.time() - float(st["t0"])
        r.hset("state:training", mapping={"active": 0, "score": elapsed})
        st.update(active="0", score=str(elapsed))
    return st


def grade(score: float, par: float) -> str:
    if score <= par:
        return "EXPERT — under par"
    if score <= 2 * par:
        return "OPERATOR — solid recovery"
    return "TRAINEE — review the fault-analysis workflow"
