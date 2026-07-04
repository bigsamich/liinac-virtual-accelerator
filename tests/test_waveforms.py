"""Intra-pulse waveform synthesis + diag-sim integration."""
import fakeredis
import numpy as np
import pytest

from pip2va.common import codec, keys
from pip2va.services.beam_physics.main import BeamPhysicsService
from pip2va.services.diag_sim.main import DiagSimService
from pip2va.services.diag_sim.waveforms import (BEAM_MS, N_SAMPLES,
                                                WaveformSynth, t_ms)


def test_envelope_shape():
    s = WaveformSynth(np.random.default_rng(1))
    env = s.envelope()
    t = t_ms()
    assert env.shape == (N_SAMPLES,)
    assert env[0] == 0.0                          # before rise
    assert env[t > BEAM_MS].max() == 0.0          # after beam window
    mid = env[(t > 0.1) & (t < 0.4)]
    assert mid.min() > 0.9                        # flat top with mild droop


def test_toroid_waveform_average_matches_current():
    s = WaveformSynth(np.random.default_rng(2))
    wf = s.toroid(2.0)
    t = t_ms()
    flat = wf[(t > 0.05) & (t < 0.5)]
    assert np.mean(flat) == pytest.approx(2.0, rel=0.05)


def test_blm_waveform_bursts_nonnegative():
    s = WaveformSynth(np.random.default_rng(3))
    wf = s.blm(0.5)
    assert wf.min() >= 0.0
    assert wf.max() > 0.5   # bursts exceed the mean level


@pytest.fixture()
def stack():
    r = fakeredis.FakeStrictRedis()
    beam = BeamPhysicsService(redis_client=r, macro=False)
    beam.on_start()
    diag = DiagSimService(redis_client=r)
    diag.on_start()
    return r, beam, diag


def test_toroid_waveform_stream(stack):
    r, beam, diag = stack
    beam.on_tick(1)
    diag.on_tick(1)
    entries = r.xrevrange(keys.stream("wf.toroid"), count=1)
    pid, data = codec.unpack(entries[0][1][b"d"])
    assert pid == 1
    assert "t_ms" in data
    assert data["BTL:TOR1"].shape == (N_SAMPLES,)


def test_capture_selected_bpm(stack):
    r, beam, diag = stack
    r.hset(keys.settings("wfsel", "main"), "devices", "SSR2:BPM5,HWR:BLM1")
    beam.on_tick(1)
    diag.on_tick(1)
    entries = r.xrevrange(keys.stream("wf.capture"), count=1)
    _, data = codec.unpack(entries[0][1][b"d"])
    assert "SSR2:BPM5:x" in data and "SSR2:BPM5:sum" in data
    assert "HWR:BLM1:wpm" in data
    assert data["SSR2:BPM5:x"].shape == (N_SAMPLES,)


def test_postmortem_on_trip(stack):
    r, beam, diag = stack
    beam.on_tick(7)
    diag.on_tick(7)
    diag.on_event(keys.CH_MPS, {"permit": 0, "blm": "LB650:BLM3"})
    pid, data = codec.unpack(r.get("wf:postmortem"))
    assert pid == 7
    blm_keys = [k for k in data if k.startswith("blm:")]
    assert len(blm_keys) >= 40
