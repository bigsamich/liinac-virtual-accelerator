"""Envelope engine physics validation."""
import numpy as np
import pytest

from pip2va.common.lattice import Lattice, Element, Section, load_lattice
from pip2va.physics.envelope import EnvelopeEngine, DesignState


def fodo_lattice(ncells=20, lcell=2.0, k1=2.2, lq=0.2):
    """Zero-current FODO channel at fixed energy for stability checks."""
    els, s = [], 0.0

    def add(name, typ, length, **params):
        nonlocal s
        els.append(Element(name=name, type=typ, s=s, length=length,
                           section="FODO", aperture_radius=0.05,
                           params=params.get("params", {}),
                           knobs=params.get("knobs", {})))
        s += length

    ld = (lcell - 2 * lq) / 2
    for i in range(ncells):
        add(f"F{i}", "quad", lq, params={"grad_per_amp": 0.1,
            "design_current": 10 * k1 * 4.88, "design_grad": k1 * 4.88})
        add(f"D1{i}", "drift", ld)
        add(f"D{i}", "quad", lq, params={"grad_per_amp": 0.1,
            "design_current": -10 * k1 * 4.88, "design_grad": -k1 * 4.88})
        add(f"D2{i}", "drift", ld)
    return Lattice(
        meta={"mass_mev": 939.294, "nominal_current_ma": 0.0,
              "peak_current_ma": 0.0, "emit_t_um": 0.25, "emit_l_um": 0.3,
              "bunch_freq_mhz": 162.5, "pulse_hz": 20.0, "pulse_ms": 0.55,
              "chop_fraction": 0.6, "loss_warn_wpm": 0.1, "loss_limit_wpm": 1.0},
        sections=[Section(name="FODO", s_start=0, s_end=s, w_in=800.0, w_out=800.0)],
        elements=els)


def test_fodo_envelope_bounded():
    """Matched-ish beam through a stable zero-current FODO stays bounded."""
    lat = fodo_lattice()
    eng = EnvelopeEngine(lat, w_init=800.0)
    res = eng.run({}, current_ma=0.0)
    assert res.transmission[-1] > 0.999
    # envelope must not blow up: max sigma over channel < 4x min
    assert res.sig_x.max() < 4.0 * res.sig_x.min()
    assert np.all(np.isfinite(res.sig_x))


@pytest.fixture(scope="module")
def full():
    lat = load_lattice()
    eng = EnvelopeEngine(lat)
    res = eng.run({})
    return lat, eng, res


def test_design_final_energy(full):
    _, _, res = full
    assert res.w[-1] == pytest.approx(800.0, abs=25.0)


def test_design_transmission(full):
    _, _, res = full
    assert res.transmission[-1] > 0.99


def test_design_losses_below_limit(full):
    lat, _, res = full
    # design machine keeps losses below the 1 W/m hands-on limit everywhere
    # downstream of the MEBT absorber region
    i0 = next(i for i, e in enumerate(lat.elements) if e.section == "HWR")
    assert res.loss_wpm[i0:].max() < 1.0


def test_bpm_samples_shape(full):
    lat, _, res = full
    nbpm = len(lat.instruments("bpm"))
    assert res.bpm_x.shape == (nbpm,)
    assert res.bpm_phase.shape == (nbpm,)
    assert np.all(np.abs(res.bpm_x) < 5e-3)  # design orbit ~centered


def test_corrector_moves_orbit_linearly(full):
    lat, eng, res0 = full
    corr = next(e for e in lat.elements
                if e.type == "corrector" and e.section == "SSR2")
    r1 = eng.run({corr.name: {"current_x": 2.0}})
    r2 = eng.run({corr.name: {"current_x": 4.0}})
    d1 = r1.bpm_x - res0.bpm_x
    d2 = r2.bpm_x - res0.bpm_x
    assert np.abs(d1).max() > 1e-5           # visible offset
    ratio = np.abs(d2).max() / np.abs(d1).max()
    assert ratio == pytest.approx(2.0, rel=0.05)  # linear response


def test_cavity_trip_kills_energy(full):
    lat, eng, res0 = full
    cav = next(e for e in lat.elements
               if e.type == "rfgap" and e.section == "LB650")
    res = eng.run({cav.name: {"status": "tripped"}})
    assert res.w[-1] < res0.w[-1] - 5.0   # lost at least this cavity's gain


def test_beam_off(full):
    lat, eng, _ = full
    res = eng.run({}, beam_on=False)
    assert res.toroid_i.max() == 0.0
    assert res.transmission[-1] == 0.0
