"""Analytic checks of the transfer-map library."""
import math

import numpy as np
import pytest

from pip2va.physics import kinematics as kin
from pip2va.physics import maps

M = 939.294


def test_beta_gamma_relativistic_limits():
    beta, gamma = kin.beta_gamma(800.0)
    assert gamma == pytest.approx(1.0 + 800.0 / M)
    assert beta == pytest.approx(math.sqrt(1 - 1 / gamma**2))
    beta_lo, _ = kin.beta_gamma(0.03)
    assert beta_lo == pytest.approx(math.sqrt(2 * 0.03 / M), rel=1e-3)  # NR limit


def test_brho_800mev():
    # p = sqrt(W^2 + 2WM) = 1463.06 MeV/c at 800 MeV -> Brho = p/299.79 = 4.88 T*m
    assert kin.brho(800.0) == pytest.approx(4.88, rel=0.01)


def test_drift_map():
    M6 = maps.drift(2.0, *kin.beta_gamma(2.1))
    v = M6 @ np.array([1e-3, 2e-3, 0, 0, 0, 0])
    assert v[0] == pytest.approx(1e-3 + 2.0 * 2e-3)
    assert v[1] == pytest.approx(2e-3)
    # longitudinal: z advances by L*delta/gamma^2 for dp/p
    beta, gamma = kin.beta_gamma(2.1)
    v2 = M6 @ np.array([0, 0, 0, 0, 0, 1e-3])
    assert v2[4] == pytest.approx(2.0 * 1e-3 / gamma**2)


def test_thick_quad_focus_thin_limit():
    beta, gamma = kin.beta_gamma(185.0)
    k1 = 4.0  # 1/m^2
    L = 0.01  # thin
    M6 = maps.quad(L, k1, beta, gamma)
    # thin-lens: x' kick = -k1*L*x
    v = M6 @ np.array([1e-3, 0, 0, 0, 0, 0])
    assert v[1] == pytest.approx(-k1 * L * 1e-3, rel=1e-3)
    # defocusing in y
    v = M6 @ np.array([0, 0, 1e-3, 0, 0, 0])
    assert v[3] == pytest.approx(+k1 * L * 1e-3, rel=1e-3)


def test_quad_determinant_unity():
    beta, gamma = kin.beta_gamma(35.0)
    M6 = maps.quad(0.2, 6.0, beta, gamma)
    assert np.linalg.det(M6) == pytest.approx(1.0, abs=1e-9)


def test_solenoid_larmor_rotation():
    """A particle offset in x rotates toward y by the Larmor angle B*L/(2*Brho)."""
    W = 10.3
    beta, gamma = kin.beta_gamma(W)
    brho = kin.brho(W)
    B, L = 0.5, 0.4
    M6 = maps.solenoid(L, B, brho, beta, gamma)
    theta = B * L / (2 * brho)
    v = M6 @ np.array([1e-3, 0, 0, 0, 0, 0])
    # rotation coupling: y picks up -sin(theta)*... nonzero coupling
    assert abs(v[2]) > 0
    assert np.linalg.det(M6[:4, :4]) == pytest.approx(1.0, abs=1e-9)
    # focusing: on-axis parallel beam converges in both planes
    vx = M6 @ np.array([1e-3, 0, 0, 0, 0, 0])
    # <x*x'> component of pure offset becomes negative (focusing) for cos<1
    assert (vx[0] * vx[1] + vx[2] * vx[3]) < 0


def test_rfgap_on_crest_gain_no_defocus():
    W_out, M6, dphi = maps.rfgap_kick(100.0, 5.0, 0.0, 650.0)
    assert W_out == pytest.approx(105.0)
    # on crest sin(phi)=0 -> no transverse defocusing
    assert M6[1, 0] == pytest.approx(0.0, abs=1e-12)
    assert M6[3, 2] == pytest.approx(0.0, abs=1e-12)


def test_rfgap_off_crest_defocuses_transverse():
    """phi < 0 (bunching side): longitudinally focusing, transversely defocusing."""
    W_out, M6, dphi = maps.rfgap_kick(100.0, 5.0, -30.0, 650.0)
    assert W_out == pytest.approx(100.0 + 5.0 * math.cos(math.radians(-30)))
    assert M6[1, 0] > 0        # transverse defocus: x' kick same sign as x
    assert M6[5, 4] != 0.0     # longitudinal focusing term present


def test_corrector_kick_adds_angle():
    dc = maps.corrector_kick(1e-3, -2e-3)
    assert dc[1] == pytest.approx(1e-3)
    assert dc[3] == pytest.approx(-2e-3)
    assert dc[0] == dc[2] == dc[4] == dc[5] == 0
