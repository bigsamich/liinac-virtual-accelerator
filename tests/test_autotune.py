"""Autotune service: restore-to-design and SVD orbit correction."""
import fakeredis
import numpy as np
import pytest

from pip2va.common import audit, keys
from pip2va.services.autotune.main import AutotuneService
from pip2va.services.beam_physics.main import BeamPhysicsService
from pip2va.services.diag_sim.main import DiagSimService
from pip2va.services.magnet_sim.main import MagnetSimService


@pytest.fixture(scope="module")
def stack():
    r = fakeredis.FakeStrictRedis()
    mag = MagnetSimService(redis_client=r)
    mag.on_start()
    beam = BeamPhysicsService(redis_client=r, macro=False)
    beam.on_start()
    diag = DiagSimService(redis_client=r)
    diag.on_start()
    tune = AutotuneService(redis_client=r)
    tune.on_start()
    tune.cadence = 3   # fast test cadence
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(keys.CH_SETTINGS)
    return r, mag, beam, diag, tune, ps


def run_pulses(stack, n, start=1):
    """Tick all services, relaying settings.changed events like Service.run."""
    r, mag, beam, diag, tune, ps = stack
    import json
    for k in range(start, start + n):
        while (m := ps.get_message(timeout=0)) is not None:
            if m["type"] == "message":
                data = json.loads(m["data"])
                mag.on_event(keys.CH_SETTINGS, data)
        mag.on_tick(k)
        beam.on_tick(k)
        diag.on_tick(k)
        tune.on_tick(k)
    return start + n


def test_restore_returns_setpoints_to_design_and_clears_faults(stack):
    r, mag, beam, diag, tune, ps = stack
    lat = tune.lat
    q = next(e for e in lat.elements if e.type == "quad" and e.section == "MEBT")
    design = q.params["design_current"]
    r.hset(keys.settings("magnet", q.name), "current", design * 1.5)
    r.hset(keys.fault("rf", "HWR:CAV2"), mapping={"type": "trip", "magnitude": 1})
    mag.on_event(keys.CH_SETTINGS, {"key": keys.settings("magnet", q.name)})

    r.set("state:mps.permit", 1)   # no MPS service in this fixture
    r.hset(keys.settings("autotune", "main"), "restore", 1)
    pulse = run_pulses(stack, 3 * 80)

    assert not r.exists(keys.fault("rf", "HWR:CAV2"))
    cur = float(r.hget(keys.settings("magnet", q.name), "current"))
    assert cur == pytest.approx(design, rel=0.01)
    assert float(r.hget(keys.settings("autotune", "main"), "restore")) == 0
    # audit trail recorded autotune writes
    entries = audit.read_log(r, 5)
    assert entries and any(e["source"] in ("autotune", "restore")
                           for e in entries)


def test_orbit_correction_reduces_rms(stack):
    r, mag, beam, diag, tune, ps = stack
    lat = tune.lat
    # perturb: kick two correctors hard
    for name in ("SSR1:C3", "SSR2:C8"):
        r.hset(keys.settings("magnet", name), "current_x", 3.0)
        mag.on_event(keys.CH_SETTINGS, {"key": keys.settings("magnet", name)})
    pulse = run_pulses(stack, 40, start=10_000)

    def orbit_rms():
        from pip2va.common import codec
        xs = [codec.unpack(f[b"d"])[1]["x"]
              for _, f in r.xrevrange(keys.stream("bpm.orbit"), count=10)]
        return float(np.sqrt(np.mean(np.concatenate(xs) ** 2)))

    rms0 = orbit_rms()
    r.hset(keys.settings("autotune", "main"), "enable", 1)
    run_pulses(stack, 3 * 30, start=20_000)
    rms1 = orbit_rms()
    r.hset(keys.settings("autotune", "main"), "enable", 0)
    # converges to the noise-floor deadband (250 um) and holds there —
    # continuing past the floor is the corrector-runaway failure mode
    assert rms1 < 300e-6, f"orbit rms {rms0*1e6:.0f} -> {rms1*1e6:.0f} um"
    assert rms1 < 0.8 * rms0
