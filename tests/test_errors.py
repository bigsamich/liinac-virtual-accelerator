"""Machine imperfections: misaligned transport + BPM systematics."""
import numpy as np
import pytest
import yaml
from importlib import resources

from pip2va.common.lattice import load_lattice
from pip2va.physics.envelope import EnvelopeEngine


@pytest.fixture(scope="module")
def errors():
    raw = (resources.files("pip2va.lattice") / "errors.yaml").read_text()
    return yaml.safe_load(raw)["errors"]


def test_errors_file_covers_machine(errors):
    lat = load_lattice()
    mags = [e for e in lat.elements if e.type in ("solenoid", "quad")]
    bpms = lat.instruments("bpm")
    assert all(e.name in errors for e in mags)
    assert all(e.name in errors for e in bpms)
    dxs = np.array([errors[e.name]["dx"] for e in mags])
    assert 0.02e-3 < dxs.std() < 0.12e-3     # survey-scale, pre-steered


def test_misalignments_bend_orbit_but_machine_survives(errors):
    lat = load_lattice()
    ideal = EnvelopeEngine(lat).run({})
    built = EnvelopeEngine(lat, errors=errors).run({})
    assert np.abs(ideal.bpm_x).max() < 0.2e-3          # ideal: straight
    assert np.abs(built.bpm_x).max() > 1.0e-3          # as-built: wanders
    assert built.transmission[-1] > 0.98               # ...but alive
    assert built.w[-1] == pytest.approx(800.0, abs=25.0)


def test_single_offset_quad_kicks_downstream():
    lat = load_lattice()
    q = next(e for e in lat.elements
             if e.type == "quad" and e.section == "LB650")
    res = EnvelopeEngine(lat, errors={q.name: {"dx": 3e-4, "dy": 0.0}}).run({})
    i_q = next(i for i, e in enumerate(lat.elements) if e.name == q.name)
    up = res.cx[:i_q]
    down = res.cx[i_q + 5:]
    assert np.abs(up).max() < 1e-5           # nothing upstream
    assert np.abs(down).max() > 1e-5         # kicked downstream
