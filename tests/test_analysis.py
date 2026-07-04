"""Trip root-cause analysis: evidence collection, rules, LLM fallback."""
import time

import fakeredis
import numpy as np

from pip2va.analysis import llm, root_cause
from pip2va.common import audit, codec, keys
from pip2va.common.lattice import load_lattice


def build_trip_scene(r, lat):
    now = time.time()
    # a cavity tripped upstream, a GUI setpoint change shortly before the trip
    r.hset(keys.readback("rf", "SSR2:CAV10"), mapping={
        "amp": 0.0, "phase": -23.0, "detuning_hz": 5.0, "status": "tripped"})
    audit.log_setting(r, keys.settings("rf", "SSR2:CAV10"), "amp", 9.9, "gui")
    r.xadd(keys.stream("mps.events"),
           {"t": now - 2, "kind": "device_fault",
            "detail": "readback:rf:SSR2:CAV10"})
    r.xadd(keys.stream("mps.events"),
           {"t": now + 0.5, "kind": "trip",
            "detail": "LB650:BLM3 55.00 W/m (limit 1.00)"})
    nblm = len(lat.instruments("blm"))
    wpm = np.full(nblm, 0.01, dtype=np.float32)
    wpm[30] = 55.0
    r.xadd(keys.stream("blm.losses"), {"d": codec.pack(1, {"wpm": wpm})})
    r.hset("state:beam", mapping={"w_out": 180.0, "transmission": 0.0,
                                  "pulse_id": 100, "permit": 0})


def test_evidence_and_rules():
    r = fakeredis.FakeStrictRedis()
    lat = load_lattice()
    build_trip_scene(r, lat)
    ev = root_cause.collect_evidence(r, lat)
    assert ev["trip"]["detail"].startswith("LB650:BLM3")
    assert ev["trip_blm_section"] == "LB650"
    tripped = [d["device"] for d in ev["tripped_devices"]]
    assert "SSR2:CAV10" in tripped
    assert all(d["upstream_of_loss"] for d in ev["tripped_devices"])
    assert any(c["key"].endswith("SSR2:CAV10") and c["source"] == "gui"
               for c in ev["setting_changes_before_trip"])

    text = root_cause.rule_based_summary(ev)
    assert "SSR2:CAV10" in text
    assert "TRIP: LB650:BLM3" in text


def test_llm_falls_back_to_rules_when_unreachable():
    r = fakeredis.FakeStrictRedis()
    lat = load_lattice()
    build_trip_scene(r, lat)
    ev = root_cause.collect_evidence(r, lat)
    text, engine = llm.analyze(ev, url="http://localhost:1", timeout=1.0)
    assert engine == "rules"
    assert "SSR2:CAV10" in text
