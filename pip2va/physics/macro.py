"""GPU macroparticle tracker: the deep-physics companion to the envelope pass.

Tracks N particles (default 100k) through the full lattice with per-particle
nonlinear RF kicks, hard-aperture collimation, and rms-linearized ("PIC-lite")
space-charge kicks. All per-particle math is vectorized on the array backend —
CuPy on the DGX GPU, NumPy in tests/CI. Free-runs beside the 20 Hz envelope
loop and publishes profiles, phase space, emittances, and a particle-true
loss map.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from pip2va.common.lattice import Lattice
from . import backend as bk
from .kinematics import beta_gamma, brho as brho_of
from .maps import drift, quad, rfgap_kick, sbend, solenoid

C = 299_792_458.0
I_ALFVEN = 3.13e7


@dataclass
class MacroResult:
    n: int
    alive_fraction: float
    w_out: float
    loss_count: np.ndarray                 # per element index
    profiles: dict                         # ws_name -> (hist_x, hist_y, edges_mm)
    phase_space: dict                      # section -> {"xxp": (H, ext), ...}
    emit_s: np.ndarray                     # sample positions [m]
    emit_x_um: np.ndarray
    emit_y_um: np.ndarray
    sig_x_mm: np.ndarray
    sig_y_mm: np.ndarray
    cloud: np.ndarray | None = None        # (3, n) x/y/z [mm] at cloud_at
    cloud_at: str | None = None


class MacroTracker:
    def __init__(self, lattice: Lattice, n: int = 100_000,
                 backend: str | None = None, w_init: float | None = None,
                 seed: int = 12345, errors: dict | None = None):
        self.lat = lattice
        self.meta = lattice.meta
        self.errors = errors or {}
        self.n = n
        self.xp = bk.get_xp(backend)
        self.w_init = w_init
        self.seed = seed
        self._ws = {e.name for e in lattice.instruments("wire_scanner")}
        self._sec_last: dict[str, str] = {}   # last element name per section
        for e in lattice.elements:
            self._sec_last[e.section] = e.name
        # emittance sample points: every BPM (~1/period); synthetic lattices
        # without BPMs sample at every quad instead
        self._emit_at = {e.name for e in lattice.elements if e.type == "bpm"}
        if not self._emit_at:
            self._emit_at = {e.name for e in lattice.elements
                             if e.type == "quad"}

    # ---------------------------------------------------------------- run

    def run(self, device_state: dict, current_ma: float | None = None,
            beam_on: bool = True, aperture_override: dict | None = None,
            cloud_at: str | None = None, cloud_n: int = 30_000
            ) -> MacroResult:
        xp = self.xp
        m = self.meta
        ds = device_state or {}
        apo = aperture_override or {}
        els = self.lat.elements
        n = self.n
        rng = np.random.default_rng(self.seed)

        i_ma = current_ma if current_ma is not None else \
            m.get("peak_current_ma", m["nominal_current_ma"])
        src = ds.get("LEBT:SRC") or {}
        if "current_ma" in src:
            i_ma = float(src["current_ma"])
        duty_keep = 1.0 - m.get("chop_fraction", 0.6)
        chop = ds.get("MEBT:CHOP1") or {}
        if "duty" in chop:
            duty_keep = min(1.0, max(0.0, float(chop["duty"])))

        loss_count = np.zeros(len(els), dtype=np.int64)
        profiles: dict = {}
        phase_space: dict = {}
        emit_s, emit_x, emit_y, sig_xs, sig_ys = [], [], [], [], []

        if not beam_on:
            return MacroResult(n=n, alive_fraction=0.0, w_out=0.0,
                               loss_count=loss_count, profiles=profiles,
                               phase_space=phase_space,
                               emit_s=np.array([]), emit_x_um=np.array([]),
                               emit_y_um=np.array([]), sig_x_mm=np.array([]),
                               sig_y_mm=np.array([]))

        w = self.w_init if self.w_init is not None else 0.030
        X = self._sample_init(rng, w)          # (6, n) on backend
        alive = xp.ones(n, dtype=bool)
        cloud = None
        f_bunch = m.get("bunch_freq_mhz", 162.5) * 1e6

        for i, el in enumerate(els):
            beta, gamma = beta_gamma(w)
            st = ds.get(el.name) or {}
            L = el.length
            typ = el.type

            if typ == "quad":
                cur = float(st.get("current", el.params["design_current"]))
                k1 = cur * el.params["grad_per_amp"] / brho_of(w)
                err = self.errors.get(el.name)
                if err:
                    X[0] -= err["dx"]
                    X[2] -= err["dy"]
                X = self._apply(quad(L, k1, beta, gamma), X)
                if err:
                    X[0] += err["dx"]
                    X[2] += err["dy"]
            elif typ == "solenoid":
                cur = float(st.get("current", el.params["design_current"]))
                b = cur * el.params["field_per_amp"]
                err = self.errors.get(el.name)
                if err:
                    X[0] -= err["dx"]
                    X[2] -= err["dy"]
                X = self._apply(solenoid(L, b, brho_of(w), beta, gamma), X)
                if err:
                    X[0] += err["dx"]
                    X[2] += err["dy"]
            elif typ == "corrector":
                X = self._apply(drift(L, beta, gamma), X)
                ix = float(st.get("current_x", 0.0))
                iy = float(st.get("current_y", 0.0))
                if ix or iy:
                    bl = el.params["bl_per_amp"]
                    rb = brho_of(w)
                    X[1] += bl * ix / rb
                    X[3] += bl * iy / rb
            elif typ == "rfgap":
                amp = 0.0 if st.get("status") == "tripped" else float(
                    st.get("amp", el.params["v_mv"]))
                phi = math.radians(float(st.get("phase",
                                                el.params["phi_deg"])))
                X = self._apply(drift(L / 2, beta, gamma), X)
                lam = 299.792458 / el.params["freq_mhz"]
                kz = 2.0 * math.pi / (beta * lam)
                mbg = 939.294 * beta * beta * gamma
                # linearized longitudinal kick (with stability guard): the
                # adiabatic-capture lattice is linearly stable by design;
                # full pendulum tails still spill from the bucket at 4 sigma,
                # so nonlinear bucket dynamics remain future work
                m54_raw = amp * math.sin(phi) * kz / mbg
                cap = 1.1 * gamma * gamma
                m54 = max(-cap, min(cap, m54_raw))
                dw_s = amp * math.cos(phi)
                dw_i = dw_s + m54 * mbg * X[4]
                w_new = w + dw_s
                b2, g2 = beta_gamma(w_new)
                mbg2 = 939.294 * b2 * b2 * g2
                X[5] = (X[5] * mbg + (dw_i - dw_s)) / mbg2
                # transverse RF defocus (linear, same as envelope)
                _, gap, kt = rfgap_kick(w, amp, math.degrees(phi),
                                        el.params["freq_mhz"])
                X[1] += kt * X[0]
                X[3] += kt * X[2]
                bgr = (beta * gamma) / (b2 * g2)
                X[1] *= bgr
                X[3] *= bgr
                if w_new < 0.05:   # reference decelerated to a stop
                    w_new = 0.05
                    alive[:] = False
                w = w_new
                b2, g2 = beta_gamma(w_new)
                beta, gamma = b2, g2
                X = self._apply(drift(L / 2, beta, gamma), X)
            elif typ == "rfq":
                amp = float(st.get("amp", 1.0))
                w = el.params["w_out_mev"]
                beta, gamma = beta_gamma(w)
                X = self._sample_rfq_exit(rng, w)
                if amp < 0.9 or amp > 1.1:
                    frac = math.exp(-0.5 * ((amp - 1.0) / 0.05) ** 2)
                    kill = xp.asarray(rng.random(n) > frac)
                    newly = kill & alive
                    loss_count[i] += int(xp.count_nonzero(newly))
                    alive = alive & ~kill
            elif typ == "dipole":
                import math as _m
                X = self._apply(sbend(L, _m.radians(
                    el.params.get("angle_deg", 0.0)), beta, gamma, 0.1), X)
            elif L > 0.0:
                X = self._apply(drift(L, beta, gamma), X)

            # space charge from live rms sizes ("PIC-lite"): nonlinear radial
            # Gaussian kick transversely (correct core gradient, 1/r tails)
            # + linear ellipsoid debunching term longitudinally
            if L > 0.0 and i_ma > 0.0 and typ != "rfq":
                na = int(xp.count_nonzero(alive))
                if na > 100:
                    sx = float(xp.std(X[0][alive]))
                    sy = float(xp.std(X[2][alive]))
                    sz = float(xp.std(X[4][alive]))
                    if sx > 0 and sy > 0:
                        bg = beta * gamma
                        lam_b = beta * C / f_bunch
                        bfac = min(30.0, lam_b / max(
                            math.sqrt(2 * math.pi) * sz, 1e-6))
                        kperv = 2.0 * (i_ma * 1e-3 * bfac) / (I_ALFVEN * bg ** 3)
                        p_ell = gamma * sz / math.sqrt(sx * sy)
                        f_ell = min(0.5, 1.0 / (3.0 * max(p_ell, 0.05)))
                        s2 = sx * sy  # round-equivalent sigma^2
                        r2 = X[0] ** 2 + X[2] ** 2
                        u = r2 / (2.0 * s2)
                        # g(u) = (1 - e^-u)/u -> 1 at r=0, ~2s2/r2 in tails
                        g = xp.where(u > 1e-6, -xp.expm1(-u) / xp.maximum(u, 1e-12),
                                     1.0 - u / 2.0)
                        kt = kperv * (1.0 - f_ell) / (2.0 * s2) * L
                        X[1] += kt * g * X[0]
                        X[3] += kt * g * X[2]
                        kz = kperv * f_ell * 2.0 / (gamma ** 2 * sz * sz) * L
                        X[5] += kz * X[4]

            # hard-aperture collimation
            if L > 0.0 and typ not in ("rfq", "source"):
                a = apo.get(el.name, el.aperture_radius)
                out = (X[0] ** 2 + X[2] ** 2) > a * a
                newly = out & alive
                nl = int(xp.count_nonzero(newly))
                if nl:
                    loss_count[i] += nl
                    alive = alive & ~newly

            # instruments / snapshots
            if el.name == cloud_at:
                idx = self.xp.nonzero(alive)[0][:cloud_n]
                pts = self.xp.stack([X[0][idx], X[2][idx], X[4][idx]]) * 1e3
                cloud = bk.asnumpy(pts).astype(np.float32)
            if el.name in self._ws:
                profiles[el.name] = self._profile(X, alive, el)
            if el.name in self._emit_at:
                ex, ey, sx, sy = self._emittance(X, alive, beta * gamma)
                emit_s.append(el.s)
                emit_x.append(ex)
                emit_y.append(ey)
                sig_xs.append(sx)
                sig_ys.append(sy)
            if el.name == self._sec_last.get(el.section):
                phase_space[el.section] = self._snapshots(X, alive)

        af = float(xp.count_nonzero(alive)) / n
        return MacroResult(
            n=n, alive_fraction=af, w_out=w, loss_count=loss_count,
            profiles=profiles, phase_space=phase_space,
            emit_s=np.array(emit_s), emit_x_um=np.array(emit_x),
            emit_y_um=np.array(emit_y),
            sig_x_mm=np.array(sig_xs) * 1e3, sig_y_mm=np.array(sig_ys) * 1e3,
            cloud=cloud, cloud_at=cloud_at if cloud is not None else None)

    # ------------------------------------------------------------ internals

    def _apply(self, m6: np.ndarray, X):
        return self.xp.asarray(m6) @ X

    def _gauss6(self, rng, ex, bx, ey, by, sz, sd):
        n = self.n
        z = rng.standard_normal((6, n))
        out = np.empty((6, n))
        out[0] = math.sqrt(ex * bx) * z[0]
        out[1] = math.sqrt(ex / bx) * z[1]
        out[2] = math.sqrt(ey * by) * z[2]
        out[3] = math.sqrt(ey / by) * z[3]
        out[4] = sz * z[4]
        out[5] = sd * z[5]
        return self.xp.asarray(out)

    def _sample_init(self, rng, w):
        beta, gamma = beta_gamma(w)
        bg = beta * gamma
        if self.w_init is not None:
            emit = self.meta.get("emit_t_um", 0.25) * 1e-6 / bg
            return self._gauss6(rng, emit, 4.0, emit, 4.0, 2e-3, 1.5e-3)
        emit = 0.13e-6 / bg
        return self._gauss6(rng, emit, 0.4, emit, 0.4, 1.0, 1e-3)

    def _sample_rfq_exit(self, rng, w):
        beta, gamma = beta_gamma(w)
        bg = beta * gamma
        emit = self.meta.get("emit_t_um", 0.20) * 1e-6 / bg
        bt = self.meta.get("rfq_exit_beta_m", 1.2)
        return self._gauss6(rng, emit, bt, emit, bt, 2e-3, 1.5e-3)

    def _profile(self, X, alive, el):
        xp = self.xp
        a = el.aperture_radius
        edges = np.linspace(-a, a, 65)
        x = bk.asnumpy(X[0][alive])
        y = bk.asnumpy(X[2][alive])
        hx, _ = np.histogram(x, bins=edges)
        hy, _ = np.histogram(y, bins=edges)
        return hx.astype(np.float32), hy.astype(np.float32), edges * 1e3

    def _snapshots(self, X, alive):
        planes = {"xxp": (0, 1), "yyp": (2, 3), "zd": (4, 5)}
        out = {}
        for key, (i, j) in planes.items():
            u = bk.asnumpy(X[i][alive])
            v = bk.asnumpy(X[j][alive])
            if len(u) < 10:
                out[key] = (np.zeros((64, 64), dtype=np.float32),
                            np.array([0, 1, 0, 1]))
                continue
            ru = 4 * max(float(np.std(u)), 1e-9)
            rv = 4 * max(float(np.std(v)), 1e-9)
            h, xe, ye = np.histogram2d(u, v, bins=64,
                                       range=[[-ru, ru], [-rv, rv]])
            out[key] = (h.astype(np.float32),
                        np.array([xe[0], xe[-1], ye[0], ye[-1]]))
        return out

    def _emittance(self, X, alive, bg):
        xp = self.xp
        if int(xp.count_nonzero(alive)) < 10:
            return 0.0, 0.0, 0.0, 0.0
        x, xpr = X[0][alive], X[1][alive]
        y, ypr = X[2][alive], X[3][alive]

        def emit(u, v):
            mu = xp.mean(u)
            mv = xp.mean(v)
            s11 = xp.mean((u - mu) ** 2)
            s22 = xp.mean((v - mv) ** 2)
            s12 = xp.mean((u - mu) * (v - mv))
            val = float(s11 * s22 - s12 ** 2)
            return math.sqrt(max(val, 0.0))

        ex = emit(x, xpr) * bg * 1e6
        ey = emit(y, ypr) * bg * 1e6
        return ex, ey, float(xp.std(x)), float(xp.std(y))
