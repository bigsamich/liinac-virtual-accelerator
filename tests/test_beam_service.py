"""beam-physics service: per-tick envelope + ground-truth publication."""
import fakeredis
import pytest

from pip2va.common import codec, keys
from pip2va.services.beam_physics.main import BeamPhysicsService


@pytest.fixture()
def svc():
    r = fakeredis.FakeStrictRedis()
    s = BeamPhysicsService(redis_client=r, macro=False)
    s.on_start()
    return s


def test_tick_writes_truth_and_state(svc):
    svc.on_tick(101)
    pulse_id, data = codec.unpack(svc.r.hget(keys.truth("beam"), "d"))
    assert pulse_id == 101
    assert data["w"][-1] == pytest.approx(800.0, abs=25.0)
    assert data["bpm_x"].shape[0] >= 45
    st = svc.read_hash("state:beam")
    assert st["pulse_id"] == 101
    assert st["w_out"] == pytest.approx(800.0, abs=25.0)
    assert st["transmission"] > 0.99


def test_permit_false_transports_no_beam(svc):
    svc.r.set("state:mps.permit", 0)
    svc.on_tick(5)
    st = svc.read_hash("state:beam")
    assert st["transmission"] == 0.0
    _, data = codec.unpack(svc.r.hget(keys.truth("beam"), "d"))
    assert data["toroid_i"].max() == 0.0


def test_cold_start_flags_stale_readbacks(svc):
    # no magnet-sim/rf-sim running -> design values used, stale flagged
    svc.on_tick(1)
    st = svc.read_hash("state:beam")
    assert st["stale"] == 1.0


def test_readback_feeds_engine(svc):
    corr = next(e for e in svc.lat.elements
                if e.type == "corrector" and e.section == "SSR1")
    svc.on_tick(1)
    _, d0 = codec.unpack(svc.r.hget(keys.truth("beam"), "d"))
    svc.r.hset(keys.readback("magnet", corr.name),
               mapping={"current_x": 5.0, "status": "ok"})
    svc.on_tick(2)
    _, d1 = codec.unpack(svc.r.hget(keys.truth("beam"), "d"))
    assert abs(d1["bpm_x"] - d0["bpm_x"]).max() > 1e-5
