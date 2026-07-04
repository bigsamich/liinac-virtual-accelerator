"""Beam-study planning validation + service-side executor."""
import json

import fakeredis
import pytest

from pip2va.analysis import studies
from pip2va.common import keys
from pip2va.services.autotune.main import AutotuneService
from pip2va.services.beam_physics.main import BeamPhysicsService
from pip2va.services.diag_sim.main import DiagSimService
from pip2va.services.magnet_sim.main import MagnetSimService


def test_validate_clamps_to_limits():
    plan = {"name": "t", "kind": "sweep", "steps": 5, "dwell_s": 1.0,
            "sweeps": [{"cls": "rf", "device": "SSR2:CAV17",
                        "field": "amp", "from": 0.0, "to": 99.0}]}
    plan, note = studies.validate_plan(plan)
    assert plan["sweeps"][0]["to"] <= 5.5      # quench-limit clamp
    assert "clamped" in note


def test_validate_rejects_bad_target():
    with pytest.raises(ValueError):
        studies.validate_plan({"name": "x", "steps": 3, "dwell_s": 1,
                               "sweeps": [{"cls": "rf", "device": "NOPE",
                                           "field": "banana",
                                           "from": 0, "to": 1}]})


def test_executor_runs_and_restores():
    r = fakeredis.FakeStrictRedis()
    mag = MagnetSimService(redis_client=r); mag.on_start()
    beam = BeamPhysicsService(redis_client=r, macro=False); beam.on_start()
    diag = DiagSimService(redis_client=r); diag.on_start()
    tune = AutotuneService(redis_client=r); tune.on_start()
    tune.cadence = 1
    r.set("state:mps.permit", 1)

    plan = {"name": "corr-sweep", "kind": "sweep", "description": "test",
            "steps": 3, "dwell_s": 0.05, "restore": True,
            "sweeps": [{"cls": "magnet", "device": "SSR1:C3",
                        "field": "current_x", "from": -1.0, "to": 1.0}]}
    plan, _ = studies.validate_plan(plan)
    r.hset("state:study", mapping={"plan": json.dumps(plan), "run": 1})
    import pip2va.common.keys as K
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(K.CH_SETTINGS)
    for k in range(1, 60):
        while (m := ps.get_message(timeout=0)) is not None:
            if m["type"] == "message":
                mag.on_event(K.CH_SETTINGS, json.loads(m["data"]))
        mag.on_tick(k); beam.on_tick(k); diag.on_tick(k); tune.on_tick(k)
        if r.hget("state:study", "run") == b"0":
            break
    st = {k.decode(): v.decode() for k, v in r.hgetall("state:study").items()}
    assert st["status"] == "completed"
    result = json.loads(st["result"])
    assert len(result["steps"]) == 3
    vals = [s["set_values"][0] for s in result["steps"]]
    assert vals == pytest.approx([-1.0, 0.0, 1.0])
    assert all(s["transmission"] > 0.9 for s in result["steps"])
    # restored to original
    assert float(r.hget(keys.settings("magnet", "SSR1:C3"),
                        "current_x")) == pytest.approx(0.0)
    # rule report renders
    rep = studies.rule_report(plan, result)
    assert "best operating point" in rep


def test_presets_all_validate():
    from pip2va.analysis import study_presets
    for nm in study_presets.PRESETS:
        plan = study_presets.get_plan(nm)
        plan, _ = studies.validate_plan(plan)
        assert plan["steps"] >= 2


def test_knowledge_roundtrip(tmp_path, monkeypatch):
    from pip2va.analysis import knowledge
    monkeypatch.setattr(knowledge, "KB_PATH", tmp_path / "kb.jsonl")
    plan = {"name": "kb-test", "kind": "sweep",
            "sweeps": [{"cls": "rf", "device": "SSR2:CAV17",
                        "field": "phase", "from": -30, "to": -20}]}
    result = {"status": "aborted-trip", "steps": [
        {"set_values": [-30], "transmission": 0.99, "worst_blm": 0.5,
         "w_tof": 800, "orbit_rms_mm": 0.3},
        {"set_values": [-20], "transmission": 0.95, "worst_blm": 80.0,
         "w_tof": 799, "orbit_rms_mm": 0.4}]}
    knowledge.append(knowledge.summarize_result(plan, result))
    ctx = knowledge.context("what happens near SSR2 CAV17 phase")
    assert "trips the MPS" in ctx and "CAV17" in ctx
