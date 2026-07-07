"""Tests for the PIP-II lattice file and loader."""
import pytest

from pip2va.common.lattice import load_lattice

SECTIONS = ["LEBT","RFQ","MEBT","HWR","SSR1","SSR2","LB650","HB650","BTL","ARC1","ARC2","BINJ","BAL"]


@pytest.fixture(scope="module")
def lat():
    return load_lattice()


def test_sections_present_in_order(lat):
    seen = []
    for el in lat.elements:
        if el.section not in seen:
            seen.append(el.section)
    assert seen == SECTIONS


def test_s_monotonic_nonoverlapping(lat):
    end = 0.0
    for el in lat.elements:
        assert el.s >= end - 1e-9, f"{el.name} overlaps previous element"
        end = el.s + el.length
    assert lat.total_length == pytest.approx(end)


def test_design_energy_checkpoints(lat):
    w = {s.name: s.w_out for s in lat.sections}
    assert w["RFQ"] == pytest.approx(2.1, abs=0.1)
    assert w["HWR"] == pytest.approx(10.3, rel=0.1)
    assert w["SSR1"] == pytest.approx(35.0, rel=0.15)
    assert w["SSR2"] == pytest.approx(185.0, rel=0.1)
    assert w["HB650"] == pytest.approx(800.0, rel=0.05)


def test_cavity_energy_sum_matches_checkpoints(lat):
    """Sum of design V*cos(phi) over cavities reproduces section energy gain."""
    import math
    for sec in lat.sections:
        cavs = [e for e in lat.elements
                if e.section == sec.name and e.type == "rfgap"]
        if not cavs:
            continue
        gain = sum(e.params["v_mv"] * math.cos(math.radians(e.params["phi_deg"]))
                   for e in cavs)
        assert gain == pytest.approx(sec.w_out - sec.w_in, rel=0.02), sec.name


def test_instrument_counts(lat):
    assert len(lat.instruments("bpm")) >= 45
    assert len(lat.instruments("blm")) >= 40
    assert len(lat.instruments("toroid")) >= 7
    assert len(lat.instruments("wire_scanner")) >= 2


def test_instruments_ordered_by_s(lat):
    for typ in ("bpm", "blm", "toroid"):
        ss = [e.s for e in lat.instruments(typ)]
        assert ss == sorted(ss)


def test_knob_keys_wellformed(lat):
    for el in lat.elements:
        for knob, key in (el.knobs or {}).items():
            parts = key.split(":")
            assert parts[0] == "settings" and len(parts) >= 3, (el.name, key)


def test_every_cavity_and_magnet_has_knobs(lat):
    for el in lat.elements:
        if el.type in ("rfgap", "solenoid", "quad", "corrector"):
            assert el.knobs, f"{el.name} has no knobs"


def test_apertures_positive(lat):
    for el in lat.elements:
        assert el.aperture_radius > 0
