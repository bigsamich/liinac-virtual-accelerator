"""Macroparticle tracker validation (CPU backend, reduced N)."""
import numpy as np
import pytest

from pip2va.common.lattice import load_lattice
from pip2va.physics.envelope import EnvelopeEngine
from pip2va.physics.macro import MacroTracker

from tests.test_envelope import fodo_lattice


def test_fodo_emittance_conserved():
    lat = fodo_lattice()
    trk = MacroTracker(lat, n=20_000, backend="numpy", w_init=800.0, seed=7)
    res = trk.run({}, current_ma=0.0)
    e0 = res.emit_x_um[0]
    e1 = res.emit_x_um[-1]
    assert e1 == pytest.approx(e0, rel=0.01)
    assert res.alive_fraction > 0.999


@pytest.fixture(scope="module")
def pair():
    lat = load_lattice()
    eng = EnvelopeEngine(lat)
    trk = MacroTracker(lat, n=20_000, backend="numpy", seed=11)
    return lat, eng.run({}), trk.run({})


def test_macro_energy_matches_envelope(pair):
    _, env, mac = pair
    assert mac.w_out == pytest.approx(env.w[-1], rel=0.01)


def test_macro_survival_reasonable(pair):
    # Hard-edge apertures on full Gaussian tails + nonlinear RF phases lose a
    # few percent that the linear envelope pass cannot see — that gap is the
    # point of running both.
    _, env, mac = pair
    assert mac.alive_fraction > 0.90


def test_profiles_at_wire_scanners(pair):
    lat, _, mac = pair
    ws_names = [e.name for e in lat.instruments("wire_scanner")]
    assert set(mac.profiles.keys()) == set(ws_names)
    px, py, edges = mac.profiles[ws_names[0]]
    assert len(px) == 64 and len(py) == 64
    assert px.sum() > 0


def test_phase_space_snapshots(pair):
    lat, _, mac = pair
    assert "HB650" in mac.phase_space
    img = mac.phase_space["HB650"]["xxp"]
    assert img[0].shape == (64, 64)


def test_aperture_scrape_localized():
    lat = load_lattice()
    trk = MacroTracker(lat, n=20_000, backend="numpy", seed=3)
    scr = next(e for e in lat.elements if e.name == "MEBT:SCR1")
    res = trk.run({}, aperture_override={scr.name: 0.002})
    i_scr = next(i for i, e in enumerate(lat.elements) if e.name == scr.name)
    assert res.loss_count[i_scr] > 1000  # 2 mm jaw bites hard
