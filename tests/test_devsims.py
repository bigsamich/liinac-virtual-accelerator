"""Device-simulator services: power supplies and RF cavities."""
import fakeredis
import numpy as np
import pytest

from pip2va.common import keys
from pip2va.common.lattice import load_lattice
from pip2va.services.magnet_sim.main import MagnetSimService
from pip2va.services.rf_sim.main import RfSimService


@pytest.fixture()
def r():
    return fakeredis.FakeStrictRedis()


def test_magnet_seeds_settings_and_slews(r):
    svc = MagnetSimService(redis_client=r)
    svc.on_start()
    lat = load_lattice()
    q = next(e for e in lat.elements if e.type == "quad" and e.section == "LB650")
    i0 = q.params["design_current"]
    assert float(r.hget(keys.settings("magnet", q.name), "current")) == pytest.approx(i0)

    # step the setpoint; readback approaches exponentially (tau >> tick)
    r.hset(keys.settings("magnet", q.name), "current", i0 + 10.0)
    svc.on_event(keys.CH_SETTINGS, {"key": keys.settings("magnet", q.name)})
    vals = []
    for k in range(40):
        svc.on_tick(k + 1)
        vals.append(float(r.hget(keys.readback("magnet", q.name), "current")))
    # moved toward the new setpoint, monotonic-ish, not there instantly
    assert vals[0] < i0 + 5.0
    assert vals[-1] > i0 + 8.0
    assert vals[-1] < i0 + 10.5


def test_magnet_ripple_small(r):
    svc = MagnetSimService(redis_client=r)
    svc.on_start()
    lat = load_lattice()
    sol = next(e for e in lat.elements if e.type == "solenoid")
    vals = []
    for k in range(100):
        svc.on_tick(k + 1)
        vals.append(float(r.hget(keys.readback("magnet", sol.name), "current")))
    rel = np.std(vals) / abs(np.mean(vals))
    assert rel < 1e-3  # ripple well under 0.1%


def test_rf_seeds_and_tracks(r):
    svc = RfSimService(redis_client=r)
    svc.on_start()
    lat = load_lattice()
    cav = next(e for e in lat.elements if e.type == "rfgap" and e.section == "SSR1")
    svc.on_tick(1)
    rb = {k.decode(): v.decode() for k, v in
          r.hgetall(keys.readback("rf", cav.name)).items()}
    assert rb["status"] == "ok"
    assert float(rb["amp"]) == pytest.approx(cav.params["v_mv"], rel=0.01)


def test_rf_quench_trips_and_needs_reset(r):
    svc = RfSimService(redis_client=r)
    svc.on_start()
    lat = load_lattice()
    cav = next(e for e in lat.elements if e.type == "rfgap" and e.section == "HWR")
    skey = keys.settings("rf", cav.name)
    r.hset(skey, "amp", cav.params["quench_mv"] * 1.1)
    svc.on_event(keys.CH_SETTINGS, {"key": skey})
    svc.on_tick(1)
    rb = svc.read_hash(keys.readback("rf", cav.name))
    assert rb["status"] == "tripped"
    assert rb["amp"] == 0.0

    # lowering amp alone does NOT clear the latch
    r.hset(skey, "amp", cav.params["v_mv"])
    svc.on_event(keys.CH_SETTINGS, {"key": skey})
    svc.on_tick(2)
    assert svc.read_hash(keys.readback("rf", cav.name))["status"] == "tripped"

    # explicit reset clears it
    r.hset(skey, "reset", 1)
    svc.on_event(keys.CH_SETTINGS, {"key": skey})
    svc.on_tick(3)
    rb = svc.read_hash(keys.readback("rf", cav.name))
    assert rb["status"] == "ok"
    assert rb["amp"] > 0.0


def test_fault_injection_trips_magnet(r):
    svc = MagnetSimService(redis_client=r)
    svc.on_start()
    lat = load_lattice()
    q = next(e for e in lat.elements if e.type == "quad")
    r.hset(keys.fault("magnet", q.name), mapping={"type": "trip", "magnitude": 1})
    svc.on_tick(1)
    rb = svc.read_hash(keys.readback("magnet", q.name))
    assert rb["status"] == "tripped"
    assert rb["current"] == 0.0


def test_utilities_model_and_couplings():
    import json
    import numpy as np
    from pip2va.services.timing.utilities import (CRYOMODULES, P_NOM_MBAR,
                                                  UtilityModel)
    um = UtilityModel()
    p, lcw = um.step(1.0)
    assert len(p) == len(CRYOMODULES) and abs(lcw - 35.0) < 2.0
    # injected cryo offset lands only on the chosen CM
    p2, _ = um.step(1.0, cryo_offset=3.0, cryo_cm="CM-SSR2-3")
    k = [c[0] for c in CRYOMODULES].index("CM-SSR2-3")
    assert p2[k] - p[k] > 2.0
    d = json.loads(UtilityModel.pack(p2, lcw))
    assert "CM-HB650-3" in d["p_mbar"] and "lcw_c" in d


def test_bpg_patterns():
    import numpy as np
    from pip2va.common import bpg
    # booster mode: notch empty, micro-pattern inside the turn
    st = {"mode": "booster", "duty": 0.4, "turn": 100, "notch": 20}
    bits = bpg.pattern_bits(st, 200)
    assert not bits[80:100].any() and not bits[180:200].any()
    assert 0.25 < bpg.avg_duty(st) < 0.40
    # custom repeats
    st = {"mode": "custom", "pattern": "101"}
    assert list(bpg.pattern_bits(st, 6)) == [True, False, True] * 2
    # stuck bucket forces a chopped bucket to pass
    st = {"mode": "custom", "pattern": "1000", "stuck_bucket": 2}
    assert bpg.pattern_bits(st, 4)[2]
