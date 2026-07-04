"""Device limits: supply clamps and aperture-bounded BPM readings."""
import fakeredis
import numpy as np
import pytest

from pip2va.common import codec, keys
from pip2va.common.lattice import load_lattice
from pip2va.services.beam_physics.main import BeamPhysicsService
from pip2va.services.diag_sim.main import DiagSimService
from pip2va.services.magnet_sim.main import MagnetSimService


def test_lattice_carries_limits():
    lat = load_lattice()
    for el in lat.elements:
        if el.type in ("solenoid", "quad"):
            assert el.params.get("max_current", 0) > 0
        elif el.type == "corrector":
            assert el.params.get("max_amp", 0) > 0
        elif el.type == "rfgap":
            assert el.params.get("quench_mv", 0) > 0


def test_magnet_setpoint_clamped_to_supply_limit():
    r = fakeredis.FakeStrictRedis()
    svc = MagnetSimService(redis_client=r)
    svc.on_start()
    lat = load_lattice()
    q = next(e for e in lat.elements if e.type == "quad")
    lim = q.params["max_current"]
    r.hset(keys.settings("magnet", q.name), "current", lim * 3.0)
    svc.on_event(keys.CH_SETTINGS, {"key": keys.settings("magnet", q.name)})
    for k in range(200):
        svc.on_tick(k + 1)
    rb = svc.read_hash(keys.readback("magnet", q.name))
    assert rb["current"] <= lim * 1.01


def test_corrector_clamped_to_max_amp():
    r = fakeredis.FakeStrictRedis()
    svc = MagnetSimService(redis_client=r)
    svc.on_start()
    lat = load_lattice()
    c = next(e for e in lat.elements if e.type == "corrector")
    r.hset(keys.settings("magnet", c.name), "current_x", 50.0)
    svc.on_event(keys.CH_SETTINGS, {"key": keys.settings("magnet", c.name)})
    for k in range(100):
        svc.on_tick(k + 1)
    rb = svc.read_hash(keys.readback("magnet", c.name))
    assert abs(rb["current_x"]) <= c.params["max_amp"] * 1.01


def test_bpm_reading_bounded_by_aperture():
    r = fakeredis.FakeStrictRedis()
    beam = BeamPhysicsService(redis_client=r, macro=False)
    beam.on_start()
    diag = DiagSimService(redis_client=r)
    diag.on_start()
    # steer hard with a huge (unclamped, direct-readback) corrector value
    corr = next(e for e in beam.lat.elements
                if e.type == "corrector" and e.section == "MEBT")
    r.hset(keys.readback("magnet", corr.name),
           mapping={"current_x": 500.0, "status": "ok"})
    beam.on_tick(1)
    diag.on_tick(1)
    _, orbit = codec.unpack(
        r.xrevrange(keys.stream("bpm.orbit"), count=1)[0][1][b"d"])
    aps = np.array([b.aperture_radius for b in diag.bpms])
    assert np.all(np.abs(orbit["x"]) <= aps + 1e-9)
