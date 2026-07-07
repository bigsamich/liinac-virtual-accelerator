"""Per-pulse envelope engine: first-order centroid + sigma-matrix transport.

Runs the whole lattice each 20 Hz pulse from live device readbacks. The chain
is inherently sequential (each element's map depends on the energy left by the
previous RF gap), so this pass runs in NumPy on the CPU where small-matrix
chains are fastest; the GPU is reserved for the embarrassingly-parallel
macroparticle pass (macro.py). Budget: << 15 ms per pass.

Phase/energy tracking: a startup design pass records the synchronous arrival
time t_des and energy w_des at every element. At runtime each RF gap is
evaluated at phi_set + 360 f (t - t_des): if upstream cavities trip, the beam
arrives late, downstream gaps slip off-crest and the energy profile collapses
— exactly the failure mode a real linac shows.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from pip2va.common.lattice import Lattice
from . import losses as loss_mod
from .kinematics import beta_gamma, brho as brho_of
from .maps import corrector_kick, drift, quad, rfgap_kick, sbend, solenoid

C = 299_792_458.0
I_ALFVEN = 3.13e7  # A, protons/H-


@dataclass
class DesignState:
    t_des: np.ndarray          # synchronous arrival time at element entrance [s]
    w_des: np.ndarray          # design energy at element entrance [MeV]
    sigma_rfq_in: float        # design rms spot size at RFQ entrance [m]


@dataclass
class EnvelopeResult:
    s: np.ndarray
    w: np.ndarray
    cx: np.ndarray
    cy: np.ndarray
    sig_x: np.ndarray
    sig_y: np.ndarray
    sig_z: np.ndarray
    transmission: np.ndarray   # surviving fraction (excludes deliberate chop)
    loss_wpm: np.ndarray       # deposited beam power per metre [W/m]
    current_ma: np.ndarray     # transported current [mA]
    bpm_x: np.ndarray
    bpm_y: np.ndarray
    bpm_phase: np.ndarray      # deg vs 162.5 MHz reference
    bpm_sum: np.ndarray        # intensity [mA]
    blm_wpm: np.ndarray
    toroid_i: np.ndarray       # [mA]
    bpm_w: np.ndarray = None   # design-frame energy at BPMs [MeV]
    emit_x_um: float = 0.0
    emit_y_um: float = 0.0


class EnvelopeEngine:
    def __init__(self, lattice: Lattice, w_init: float | None = None,
                 errors: dict | None = None):
        self.lat = lattice
        self.meta = lattice.meta
        self.errors = errors or {}
        # live-tunable physics parameters (Physics dashboard)
        self.phys = {"sc_scale": 1.0, "ibst_scale": 1.0, "gas_scale": 1.0,
                     "pressure_torr": 1e-8, "sc_form_factor": 1.0,
                     "disp_scale": 0.1}  # residual arc dispersion (achromat)
        self.els = lattice.elements
        self.n = len(self.els)
        self.w_init = w_init
        self.duty = (self.meta.get("pulse_ms", 0.55) * 1e-3
                     * self.meta.get("pulse_hz", 20.0))
        self._bpm_idx = [i for i, e in enumerate(self.els) if e.type == "bpm"]
        self._blm_idx = [i for i, e in enumerate(self.els) if e.type == "blm"]
        self._tor_idx = [i for i, e in enumerate(self.els) if e.type == "toroid"]
        self._blm_s = np.array([self.els[i].s for i in self._blm_idx])
        # element index -> nearest BLM (within 5 m), else -1
        self._near_blm = np.full(self.n, -1, dtype=int)
        if len(self._blm_s):
            for i, e in enumerate(self.els):
                j = int(np.argmin(np.abs(self._blm_s - e.s)))
                if abs(self._blm_s[j] - e.s) < 5.0:
                    self._near_blm[i] = j
        self.design = self._design_pass()

    # ------------------------------------------------------------------ API

    emit_scale = 1.0    # dual-source legs: leg B delivers ~6% hotter beam

    def run(self, device_state: dict, current_ma: float | None = None,
            beam_on: bool = True, _design_mode: bool = False,
            errant_kick_mrad: float = 0.0) -> EnvelopeResult:
        """Transport one pulse. device_state: {element_name: {field: value}}."""
        m = self.meta
        ds = device_state or {}
        i_peak = current_ma if current_ma is not None else \
            m.get("peak_current_ma", m["nominal_current_ma"])
        # source setting overrides (peak current out of the source)
        src = ds.get("LEBT:SRC") or {}
        if "current_ma" in src:
            i_peak = float(src["current_ma"])
        duty_keep = 1.0 - m.get("chop_fraction", 0.6)
        chop = ds.get("MEBT:CHOP1") or ds.get("CHOP") or {}
        if "duty" in chop or "mode" in chop:
            from pip2va.common.bpg import avg_duty
            duty_keep = avg_duty(chop)

        n = self.n
        out = EnvelopeResult(
            s=np.array([e.s for e in self.els]),
            w=np.zeros(n), cx=np.zeros(n), cy=np.zeros(n),
            sig_x=np.zeros(n), sig_y=np.zeros(n), sig_z=np.zeros(n),
            transmission=np.zeros(n), loss_wpm=np.zeros(n),
            current_ma=np.zeros(n),
            bpm_x=np.zeros(len(self._bpm_idx)), bpm_y=np.zeros(len(self._bpm_idx)),
            bpm_phase=np.zeros(len(self._bpm_idx)),
            bpm_sum=np.zeros(len(self._bpm_idx)),
            blm_wpm=np.zeros(len(self._blm_idx)),
            toroid_i=np.zeros(len(self._tor_idx)),
            bpm_w=np.zeros(len(self._bpm_idx)),
        )
        if not beam_on:
            return out

        w = self.w_init if self.w_init is not None else 0.030
        c6 = np.zeros(6)
        c6[1] = errant_kick_mrad * 1e-3   # errant-beam source glitch
        self.scrape_out = {}
        sig = self._init_sigma(w)
        sig[:4, :4] *= self.emit_scale
        f_surv = 1.0
        i_ma = i_peak
        t = 0.0
        bpm_k = blm_k = tor_k = 0
        des = None if _design_mode else self.design
        f_bunch = m.get("bunch_freq_mhz", 162.5) * 1e6
        t_des_arr = des.t_des if des is not None else None

        for i, el in enumerate(self.els):
            beta, gamma = beta_gamma(w)
            st = ds.get(el.name) or {}
            L = el.length
            typ = el.type
            tof_done = False
            sc_done = False

            def apply_sc(Ls, _w=None):
                """Thin ellipsoid space-charge kick over length Ls."""
                nonlocal c6, sig
                if Ls <= 0.0 or i_ma <= 0.0:
                    return
                wj = w if _w is None else _w
                bj, gj = beta_gamma(wj)
                sx = math.sqrt(max(sig[0, 0], 1e-12))
                sy = math.sqrt(max(sig[2, 2], 1e-12))
                sz = math.sqrt(max(sig[4, 4], 1e-12))
                bgj = bj * gj
                lam_b = bj * C / f_bunch
                bfac = min(30.0, lam_b / max(math.sqrt(2 * math.pi) * sz, 1e-6))
                kperv = 2.0 * (i_ma * 1e-3 * bfac) / (I_ALFVEN * bgj ** 3) \
                    * self.phys.get("sc_scale", 1.0)
                p_ell = gj * sz / math.sqrt(sx * sy)
                f_ell = min(0.5, 1.0 / (3.0 * max(p_ell, 0.05))) \
                    * self.phys.get("sc_form_factor", 1.0)
                msc = np.eye(6)
                msc[1, 0] = kperv * (1 - f_ell) / (sx * (sx + sy)) * Ls
                msc[3, 2] = kperv * (1 - f_ell) / (sy * (sx + sy)) * Ls
                msc[5, 4] = kperv * f_ell * 2.0 / (gj ** 2 * sz * sz) * Ls
                c6 = msc @ c6
                sig = msc @ sig @ msc.T

            # ---- element transport
            if typ == "quad":
                cur = float(st.get("current", el.params["design_current"]))
                g = cur * el.params["grad_per_amp"]
                k1 = g / brho_of(w)
                err = self.errors.get(el.name)
                if err:  # transport in the misaligned element's frame
                    c6[0] -= err["dx"]
                    c6[2] -= err["dy"]
                nsl = max(1, int(L / 0.4))
                for _ in range(nsl):
                    mtx = quad(L / nsl, k1, beta, gamma)
                    c6 = mtx @ c6
                    sig = mtx @ sig @ mtx.T
                    apply_sc(L / nsl)
                if err:
                    c6[0] += err["dx"]
                    c6[2] += err["dy"]
                sc_done = True
            elif typ == "solenoid":
                cur = float(st.get("current", el.params["design_current"]))
                b = cur * el.params["field_per_amp"]
                err = self.errors.get(el.name)
                if err:
                    c6[0] -= err["dx"]
                    c6[2] -= err["dy"]
                nsl = max(1, int(L / 0.4))
                for _ in range(nsl):
                    mtx = solenoid(L / nsl, b, brho_of(w), beta, gamma)
                    c6 = mtx @ c6
                    sig = mtx @ sig @ mtx.T
                    apply_sc(L / nsl)
                if err:
                    c6[0] += err["dx"]
                    c6[2] += err["dy"]
                sc_done = True
            elif typ == "corrector":
                mtx = drift(L, beta, gamma)
                c6 = mtx @ c6
                sig = mtx @ sig @ mtx.T
                ix = float(st.get("current_x", 0.0))
                iy = float(st.get("current_y", 0.0))
                if ix or iy:
                    bl = el.params["bl_per_amp"]
                    rb = brho_of(w)
                    c6 = c6 + corrector_kick(bl * ix / rb, bl * iy / rb)
            elif typ == "rfgap":
                if st.get("status") == "tripped":
                    amp = 0.0
                else:
                    amp = float(st.get("amp", el.params["v_mv"]))
                phi_set = float(st.get("phase", el.params["phi_deg"]))
                dphi = 0.0
                if t_des_arr is not None:
                    # synchrotron re-centering, gated to the linear bucket:
                    # small timing errors are pulled back toward synchronous
                    # (real bunches oscillate, they don't run away), but
                    # large errors (trips) are outside the bucket and stay
                    # open-loop -> the phase-slip cascade remains fatal
                    f_hz = el.params["freq_mhz"] * 1e6
                    dphi_raw = ((360.0 * f_hz * (t - t_des_arr[i]) + 180.0)
                                % 360.0 - 180.0)
                    if abs(dphi_raw) < 30.0:
                        t = t + 0.25 * (t_des_arr[i] - t)
                    dphi = ((360.0 * f_hz * (t - t_des_arr[i]) + 180.0)
                            % 360.0 - 180.0)
                # drift through half gap, kick, drift through second half
                half = drift(L / 2.0, beta, gamma)
                c6 = half @ c6
                sig = half @ sig @ half.T
                apply_sc(L / 2.0)
                t += (L / 2.0) / (beta * C)
                w, gap, _ = rfgap_kick(w, amp, phi_set + dphi, el.params["freq_mhz"])
                if w < 0.05:   # decelerated to a stop: beam is lost, not NaN
                    w = 0.05
                    f_surv = 0.0
                c6 = gap @ c6
                sig = gap @ sig @ gap.T
                beta, gamma = beta_gamma(w)
                half = drift(L / 2.0, beta, gamma)
                c6 = half @ c6
                sig = half @ sig @ half.T
                apply_sc(L / 2.0)
                t += (L / 2.0) / (beta * C)
                tof_done = True
                sc_done = True
            elif typ == "rfq":
                # lumped RFQ: accelerates to fixed output energy and re-forms
                # the beam; detuned amplitude costs transmission.
                amp = float(st.get("amp", 1.0))
                if st.get("status") == "tripped":
                    amp = 0.0
                sig_in = math.sqrt(max(sig[0, 0], 0.0))
                if des is not None and des.sigma_rfq_in > 0:
                    ratio = sig_in / des.sigma_rfq_in
                    t_spot = math.exp(-0.5 * ((max(ratio, 1.0) - 1.0) / 0.5) ** 2)
                else:
                    t_spot = 1.0
                t_amp = math.exp(-0.5 * ((amp - 1.0) / 0.05) ** 2)
                if amp < 0.5:
                    f_surv = 0.0
                f_surv *= t_amp * t_spot
                w = el.params["w_out_mev"]
                beta, gamma = beta_gamma(w)
                c6 = np.zeros(6)
                sig = self._rfq_exit_sigma(w)
            elif typ == "scraper2":
                st = device_state.get(el.name, {})
                pos_mm = float(st.get("pos_mm", 30.0))   # 30 = retracted
                ap_eff = max(pos_mm, 0.5) * 1e-3
                sx = math.sqrt(max(sig[0, 0], 1e-12))
                sy = math.sqrt(max(sig[2, 2], 1e-12))
                axis = st.get("axis", "x")
                # one-sided jaw ~ half of the symmetric scrape fraction
                if axis == "x":
                    f_jaw = 0.5 * loss_mod.scrape_fraction(
                        ap_eff, c6[0], sx, 1.0, 0.0, sy)
                else:
                    f_jaw = 0.5 * loss_mod.scrape_fraction(
                        1.0, 0.0, sx, ap_eff, c6[2], sy)
                f_jaw = min(f_jaw, 0.5)
                if f_jaw > 1e-12 and f_surv > 0:
                    p_w = f_jaw * f_surv * i_ma * 1e-3 * self.duty * w * 1e6
                    out.loss_wpm[i] += p_w / 0.1     # deposit over 0.1 m
                    f_surv *= (1.0 - f_jaw)
                self.scrape_out[el.name] = f_jaw
            elif typ == "chopper":
                mtx = drift(L, beta, gamma)
                c6 = mtx @ c6
                sig = mtx @ sig @ mtx.T
                if el.params.get("kind") == "mebt" and el.name.endswith("CHOP1"):
                    i_ma = i_ma * duty_keep
            elif typ == "source":
                pass
            elif typ == "dipole":
                ang = math.radians(el.params.get("angle_deg", 0.0))
                mtx = sbend(L, ang, beta, gamma,
                            self.phys.get("disp_scale", 0.1))
                c6 = mtx @ c6
                sig = mtx @ sig @ mtx.T
                apply_sc(L)
                sc_done = True
            elif L > 0.0:  # drift, aperture, wire_scanner, toroid body
                nsl = max(1, int(L / 0.4))
                for _ in range(nsl):
                    mtx = drift(L / nsl, beta, gamma)
                    c6 = mtx @ c6
                    sig = mtx @ sig @ mtx.T
                    apply_sc(L / nsl)
                sc_done = True

            # ---- space charge for any remaining short elements
            if L > 0.0 and not sc_done and typ not in ("rfq", "source"):
                apply_sc(L)

            # ---- losses at this element
            if L > 0.0 and f_surv > 0.0 and typ not in ("rfq", "source"):
                sx = math.sqrt(max(sig[0, 0], 1e-12))
                sy = math.sqrt(max(sig[2, 2], 1e-12))
                sz = math.sqrt(max(sig[4, 4], 1e-12))
                a = el.aperture_radius
                f_scrape = loss_mod.scrape_fraction(a, c6[0], sx, a, c6[2], sy)
                f_base = 0.0
                if w > 2.0:  # bunched beam only (post-RFQ)
                    f_base = loss_mod.hminus_baseline_frac_per_m(
                        i_ma * f_surv, beta, gamma, sx, sy, sz,
                        thx=math.sqrt(max(sig[1, 1], 0.0)),
                        thy=math.sqrt(max(sig[3, 3], 0.0)),
                        ths=math.sqrt(max(sig[5, 5], 0.0)),
                        ibst_scale=self.phys.get("ibst_scale", 1.0),
                        gas_scale=self.phys.get("gas_scale", 1.0),
                        pressure_torr=self.phys.get(
                            "pressure_by_section", {}).get(
                            el.section,
                            self.phys.get("pressure_torr", 1e-8))) * L
                f_lost = min(1.0, f_scrape + f_base)
                if f_lost > 0.0:
                    p_w = (f_lost * f_surv * i_ma * 1e-3 * self.duty
                           * w * 1e6)
                    out.loss_wpm[i] = p_w / L
                    j = self._near_blm[i]
                    if j >= 0:
                        out.blm_wpm[j] += p_w / L
                    f_surv *= (1.0 - f_lost)

            # ---- time-of-flight
            if L > 0.0 and not tof_done:
                t += L / (beta * C)

            # ---- record + instruments
            out.w[i] = w
            out.cx[i], out.cy[i] = c6[0], c6[2]
            out.sig_x[i] = math.sqrt(max(sig[0, 0], 0.0))
            out.sig_y[i] = math.sqrt(max(sig[2, 2], 0.0))
            out.sig_z[i] = math.sqrt(max(sig[4, 4], 0.0))
            out.transmission[i] = f_surv
            out.current_ma[i] = i_ma * f_surv

            if typ == "bpm":
                out.bpm_x[bpm_k] = c6[0]
                out.bpm_y[bpm_k] = c6[2]
                if t_des_arr is not None:
                    ph = 360.0 * f_bunch * (t - t_des_arr[i])
                    out.bpm_phase[bpm_k] = (ph + 180.0) % 360.0 - 180.0
                out.bpm_sum[bpm_k] = i_ma * f_surv
                out.bpm_w[bpm_k] = w
                bpm_k += 1
            elif typ == "blm":
                blm_k += 1
            elif typ == "toroid":
                out.toroid_i[tor_k] = i_ma * f_surv
                tor_k += 1

        bg_end = np.prod(beta_gamma(out.w[-1]))
        out.emit_x_um = 1e6 * bg_end * math.sqrt(
            max(sig[0, 0] * sig[1, 1] - sig[0, 1] ** 2, 0.0))
        out.emit_y_um = 1e6 * bg_end * math.sqrt(
            max(sig[2, 2] * sig[3, 3] - sig[2, 3] ** 2, 0.0))
        return out

    # ------------------------------------------------------------- internals

    def _design_pass(self) -> DesignState:
        """Record synchronous arrival time/energy at each element entrance."""
        t_des = np.zeros(self.n)
        w_des = np.zeros(self.n)
        w = self.w_init if self.w_init is not None else 0.030
        t = 0.0
        sigma_rfq_in = 0.0
        # quick forward walk with design settings only (no sigma transport)
        for i, el in enumerate(self.els):
            t_des[i] = t
            w_des[i] = w
            if el.type == "rfgap":
                beta, _ = beta_gamma(w)
                t += (el.length / 2.0) / (beta * C)
                w = w + el.params["v_mv"] * math.cos(
                    math.radians(el.params["phi_deg"]))
                beta, _ = beta_gamma(w)
                t += (el.length / 2.0) / (beta * C)
            elif el.type == "rfq":
                w = el.params["w_out_mev"]
                beta, _ = beta_gamma(w)
                t += el.length / (beta * C)
            elif el.length > 0.0:
                beta, _ = beta_gamma(w)
                t += el.length / (beta * C)
        # design sigma at RFQ entrance via a design run (no design-state yet)
        res = self.run({}, beam_on=True, _design_mode=True,
                       current_ma=self.meta.get("peak_current_ma", 5.0))
        rfq_i = next((i for i, e in enumerate(self.els) if e.type == "rfq"), None)
        if rfq_i is not None and rfq_i > 0:
            sigma_rfq_in = float(res.sig_x[rfq_i - 1])
        return DesignState(t_des=t_des, w_des=w_des, sigma_rfq_in=sigma_rfq_in)

    def _init_sigma(self, w: float) -> np.ndarray:
        beta, gamma = beta_gamma(w)
        bg = beta * gamma
        if self.w_init is not None:
            emit = self.meta.get("emit_t_um", 0.25) * 1e-6 / bg
            return self._twiss_sigma(emit, 4.0, emit, 4.0, 2e-3, 1.5e-3)
        # LEBT source beam (measured 0.13 um at 5 mA)
        emit = 0.13e-6 / bg
        return self._twiss_sigma(emit, 0.4, emit, 0.4, 1.0, 1e-3)

    def _rfq_exit_sigma(self, w: float) -> np.ndarray:
        beta, gamma = beta_gamma(w)
        bg = beta * gamma
        emit = self.meta.get("emit_t_um", 0.20) * 1e-6 / bg
        bt = self.meta.get("rfq_exit_beta_m", 1.2)
        return self._twiss_sigma(emit, bt, emit, bt, 2e-3, 1.5e-3)

    @staticmethod
    def _twiss_sigma(ex: float, bx: float, ey: float, by: float,
                     sz: float, sdelta: float) -> np.ndarray:
        sig = np.zeros((6, 6))
        sig[0, 0] = ex * bx
        sig[1, 1] = ex / bx
        sig[2, 2] = ey * by
        sig[3, 3] = ey / by
        sig[4, 4] = sz * sz
        sig[5, 5] = sdelta * sdelta
        return sig
