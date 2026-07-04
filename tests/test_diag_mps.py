"""diag-sim (measurements) and mps (beam permit) services."""
import fakeredis
import numpy as np
import pytest

from pip2va.common import codec, keys
from pip2va.services.beam_physics.main import BeamPhysicsService
from pip2va.services.diag_sim.main import DiagSimService
from pip2va.services.mps.main import MpsService


@pytest.fixture()
def stack():
    r = fakeredis.FakeStrictRedis()
    beam = BeamPhysicsService(redis_client=r, macro=False)
    beam.on_start()
    diag = DiagSimService(redis_client=r)
    diag.on_start()
    mps = MpsService(redis_client=r, learn_pulses=0)  # armed immediately
    mps.on_start()
    return r, beam, diag, mps


def latest(r, product):
    entries = r.xrevrange(keys.stream(product), count=1)
    assert entries, f"no entries in {product}"
    return codec.unpack(entries[0][1][b"d"])


def test_orbit_stream_tracks_truth_with_noise(stack):
    r, beam, diag, _ = stack
    xs = []
    for k in range(1, 31):
        beam.on_tick(k)
        diag.on_tick(k)
        pid, orbit = latest(r, "bpm.orbit")
        xs.append(orbit["x"])
    assert pid == 30
    _, truth = codec.unpack(r.hget(keys.truth("beam"), "d"))
    xs = np.array(xs)
    resid = xs - truth["bpm_x"][None, :]
    rms_um = np.std(resid, axis=0).mean() * 1e6
    assert 2.0 < rms_um < 60.0  # noisy, but honest 10 um-class BPMs
    # intensity present
    _, orbit = latest(r, "bpm.orbit")
    assert orbit["sum"].max() > 1.0


def test_blm_and_toroid_streams(stack):
    r, beam, diag, _ = stack
    beam.on_tick(1)
    diag.on_tick(1)
    _, blm = latest(r, "blm.losses")
    _, tor = latest(r, "toroid.current")
    assert blm["wpm"].shape[0] >= 40
    assert tor["i_ma"][-1] == pytest.approx(2.0, rel=0.2)


def test_mps_trips_on_sustained_loss_and_reset_gated(stack):
    r, beam, diag, mps = stack
    assert r.get("state:mps.permit") == b"1"
    # inject sustained fake high loss directly into the measurement stream
    nblm = 46
    hot = np.zeros(nblm, dtype=np.float32)
    hot[20] = 5.0  # 5 W/m
    for k in range(1, 12):
        r.xadd(keys.stream("blm.losses"), {"d": codec.pack(k, {"wpm": hot})})
        mps.on_tick(k)
    assert r.get("state:mps.permit") == b"0"
    events = r.xrange(keys.stream("mps.events"))
    assert events

    # reset while loss persists is refused
    r.hset(keys.settings("mps", "main"), "reset", 1)
    r.xadd(keys.stream("blm.losses"), {"d": codec.pack(12, {"wpm": hot})})
    mps.on_tick(12)
    assert r.get("state:mps.permit") == b"0"

    # loss clears (beam off -> dark current), reset now accepted
    cold = np.full(nblm, 0.001, dtype=np.float32)
    for k in range(13, 26):
        r.xadd(keys.stream("blm.losses"), {"d": codec.pack(k, {"wpm": cold})})
        mps.on_tick(k)
    r.hset(keys.settings("mps", "main"), "reset", 1)
    mps.on_tick(26)
    assert r.get("state:mps.permit") == b"1"


def test_wire_scan_lifecycle(stack):
    r, beam, diag, _ = stack
    ws = diag.lat.instruments("wire_scanner")[0].name
    # seed a deep entry with a profile for this WS
    prof = np.exp(-0.5 * ((np.arange(64) - 32) / 6.0) ** 2).astype(np.float32)
    edges = np.linspace(-14, 14, 65).astype(np.float32)
    r.xadd(keys.stream("beam.deep"), {"d": codec.pack(1, {
        f"prof:{ws}:x": prof, f"prof:{ws}:y": prof,
        f"prof:{ws}:edges": edges})})
    r.hset(f"req:wire:{ws}", "plane", "x")
    done = False
    for k in range(1, 40):
        beam.on_tick(k)
        diag.on_tick(k)
        if not r.exists(f"req:wire:{ws}"):
            done = True
            break
    assert done, "scan never completed"
    _, scan = latest(r, "profile.scan")
    assert scan["name"] == ws
    assert scan["done"] == 1
    assert len(scan["pos_mm"]) == 64
