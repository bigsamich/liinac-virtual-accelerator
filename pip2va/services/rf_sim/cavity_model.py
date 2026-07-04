"""Physical SRF cavity model, vectorized across all cavities.

Integrates the standard complex-envelope equation per 20 Hz machine pulse
across the 0.55 ms window (exact exponential update; see
docs/research/srf_beamline_report.md):

    dVc/dt = -(w12 - j*dw(t))*Vc + 2*w12*Vfor + w12*RL*Ib

with a PI LLRF loop (loop delay in samples), gated beam loading
(|Ib| = 2*I_DC), gated feedforward, stochastic microphonics (OU He-pressure
drift + wandering acoustic lines + bursts), dynamic Lorentz-force detuning
(two 2nd-order mechanical modes per cavity), a slow tuner servo, and physical
quenches (Q0 collapse -> field dies inside the window).

Everything is float64/complex128 numpy arrays of shape (ncav,); the window
integration is NSTEP sequential vector steps.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# family constants from the verified research table
FAMILY = {
    #            r/Q [ohm]  L_eff[m]  kL[Hz/(MV/m)^2]  df/dp[Hz/Torr]
    "HWR":      (275.0,     0.207,    1.5,             13.0),
    "SSR1":     (242.0,     0.205,    4.4,              4.0),
    "SSR2":     (296.0,     0.438,    7.5,              3.4),
    "LB650":    (375.0,     0.746,    0.8,              3.0),
    "HB650":    (609.0,     1.120,    1.6,              3.0),
    "buncher":  (150.0,     0.20,     0.0,              0.0),
    "debuncher": (300.0,    0.60,     0.0,              0.0),
}

# SSA ratings [kW] (verified table) — absolute, NOT relative to the drive:
# de-rated capture cavities carry beam loading far above their own voltage
SSA_KW = {"HWR": 7.0, "SSR1": 7.0, "SSR2": 20.0, "LB650": 40.0,
          "HB650": 70.0, "buncher": 3.0, "debuncher": 300.0,
          "RFQ": 500.0}  # RFQ: 2x75 kW SSAs; amp is a normalized scale

WINDOW_S = 0.55e-3
BEAM_S = 0.54e-3
NSTEP = 220                    # 2.5 us steps across the window
DT = WINDOW_S / NSTEP
LOOP_DELAY = 1                 # steps (~2.5 us LLRF loop delay)
GP = 800.0                     # proportional gain (PIP2IT-class, delay-safe)
KI = 3.0e6                     # integral gain [rad/s]
MECH_MODES = ((157.0, 100.0, 0.6), (215.0, 100.0, 0.4))  # (f, Q, k-share)
LFD_COMP = 0.9   # piezo adaptive-FF compensation of dynamic LFD (90%)
LINES = (18.0, 30.0, 46.0, 60.0)          # microphonic lines [Hz]
LINE_SHARE = (0.55, 0.20, 0.15, 0.10)     # power share of the line budget


@dataclass
class CavityBank:
    """Vectorized state for all cavities."""

    names: list
    freq: np.ndarray            # [Hz]
    w12: np.ndarray             # [rad/s]
    roq: np.ndarray
    rl: np.ndarray              # 0.5*(r/Q)*QL
    leff: np.ndarray
    kl: np.ndarray              # LFD Hz/(MV/m)^2
    dfdp: np.ndarray            # He sensitivity Hz/Torr
    v_max: np.ndarray           # capability [MV]
    ssa_frac: np.ndarray        # SSA limit as multiple of nominal Vfor


class CavityModel:
    def __init__(self, cavities: list, rng: np.random.Generator,
                 tick_dt: float = 0.05):
        self.rng = rng
        self.tick_dt = tick_dt
        n = len(cavities)
        self.n = n
        fam = [c.params.get("family",
                            "RFQ" if getattr(c, "type", "") == "rfq"
                            else "buncher") for c in cavities]
        roq = np.array([FAMILY.get(f, FAMILY["buncher"])[0] for f in fam])
        leff = np.array([FAMILY.get(f, FAMILY["buncher"])[1] for f in fam])
        kl = np.array([FAMILY.get(f, FAMILY["buncher"])[2] for f in fam])
        dfdp = np.array([FAMILY.get(f, FAMILY["buncher"])[3] for f in fam])
        freq = np.array([c.params.get("freq_mhz", 162.5) * 1e6
                         for c in cavities])
        ql = np.array([c.params.get("ql", 1e4) for c in cavities])
        self.bank = CavityBank(
            names=[c.name for c in cavities],
            freq=freq, w12=2 * np.pi * freq / (2 * ql), roq=roq,
            rl=0.5 * roq * ql, leff=leff, kl=kl, dfdp=dfdp,
            v_max=np.array([c.params.get("v_max_mv",
                                         c.params.get("v_mv", 1.0))
                            for c in cavities]),
            ssa_frac=np.full(n, 2.5))
        # absolute SSA forward-voltage limit: |Vfor| <= sqrt(2 R_L P_ssa)
        p_ssa = np.array([SSA_KW.get(f, 10.0) * 1e3 for f in fam])
        self.vfor_ssa = np.sqrt(2.0 * self.bank.rl * p_ssa) * 1e-6  # MV
        # per-cavity loop gains: broadband NC cavities (RFQ/bunchers) need
        # proportionally less gain — the plant pole is already fast
        f_half = self.bank.w12 / (2 * np.pi)
        self.gp = GP * np.minimum(1.0, 60.0 / f_half)
        self.ki = KI * np.minimum(1.0, 60.0 / f_half)
        # dynamic state
        self.Vc = np.zeros(n, dtype=complex)         # cavity field [MV]
        self.int_err = np.zeros(n, dtype=complex)    # PI integrator
        self.tuner = np.zeros(n)                     # slow tuner offset [Hz]
        self.he = np.zeros(n)                        # OU He pressure [Torr]
        self.line_phase = rng.uniform(0, 2 * np.pi, (len(LINES), n))
        self.line_freq = np.array(LINES)[:, None] * np.ones((1, n))
        self.line_amp = self._line_amps(rng, n)
        self.burst = np.ones(n)                      # burst multiplier
        self.lfd_slow = np.zeros(n)                  # static LFD (lagged) [Hz]
        self.ring_amp = np.zeros((len(MECH_MODES), n))   # transient rings [Hz]
        self.ring_ph = rng.uniform(0, 2 * np.pi, (len(MECH_MODES), n))
        self._e2_prev = np.zeros(n)
        self.ext_det = np.zeros(n)                   # injected detune faults [Hz]
        self.q0_fac = np.ones(n)                     # 1 normal, >>1 quenched
        self.quenched = np.zeros(n, dtype=bool)
        self.t = 0.0

    def pretune(self, v_set: np.ndarray):
        """Cold-tuning: absorb static LFD at operating gradient (as-found
        state of a commissioned cavity) and pre-fill the field."""
        e_acc = v_set / self.bank.leff
        self.lfd_slow = -self.bank.kl * e_acc ** 2
        self.ring_amp[:] = 0.0
        self._e2_prev = e_acc ** 2
        self.tuner = self.lfd_slow.copy()
        self.Vc = v_set.astype(complex)

    @staticmethod
    def _line_amps(rng, n):
        # per-cavity total line rms 1-4 Hz, split by LINE_SHARE
        total = rng.uniform(1.0, 4.0, n)
        return (np.sqrt(np.array(LINE_SHARE))[:, None]
                * total[None, :] * np.sqrt(2.0))

    # ------------------------------------------------------------ per tick

    def microphonics_step(self):
        """Advance slow stochastic state by one machine tick."""
        rng, n, dt = self.rng, self.n, self.tick_dt
        # OU He-pressure drift (tau_c ~ 60 s, sigma 0.05 Torr)
        tau_c, sig = 60.0, 0.05
        a = np.exp(-dt / tau_c)
        self.he = self.he * a + sig * np.sqrt(1 - a * a) * rng.normal(size=n)
        # acoustic line phases wander; Helmholtz line frequency random-walks
        self.line_phase += 2 * np.pi * self.line_freq * dt \
            + rng.normal(0, 0.05, (len(LINES), n))
        self.line_freq[2] = np.clip(
            self.line_freq[2] + rng.normal(0, 0.05, n), 40.0, 56.0)
        # Poisson bursts: ~1/hour per cavity, lasting ~minutes
        start = rng.random(n) < dt / 3600.0
        decay = np.exp(-dt / 120.0)
        self.burst = 1.0 + (self.burst - 1.0) * decay + start * rng.uniform(
            2.0, 4.0, n)
        # transient LFD rings decay analytically between pulses
        t_gap = max(dt - WINDOW_S, 0.0)
        for m, (fm, qm, _) in enumerate(MECH_MODES):
            wm = 2 * np.pi * fm
            self.ring_amp[m] *= np.exp(-wm / (2 * qm) * t_gap)
            self.ring_ph[m] += wm * t_gap

    def detuning_now(self, t_in_window: float) -> np.ndarray:
        """Instantaneous detuning [Hz] for all cavities."""
        tt = self.t + t_in_window
        lines = np.sum(
            self.line_amp * self.burst[None, :]
            * np.sin(2 * np.pi * self.line_freq * t_in_window
                     + self.line_phase), axis=0)
        return (self.dfdp_he + lines + self.lfd_slow - self.tuner
                + self.ext_det)

    # ------------------------------------------------------------ window

    def run_window(self, v_set: np.ndarray, phi_set_deg: np.ndarray,
                   i_beam_ma: float, beam_on: bool, duty_keep: float,
                   tripped: np.ndarray, want_wf: list[int] | None = None):
        """Integrate one 0.55 ms window. Returns summary dict (+waveforms).

        v_set: amplitude setpoints [MV]; phi_set: synchronous phase [deg];
        i_beam_ma: pre-chop beam current; tripped: bool mask (RF off).
        """
        b = self.bank
        n = self.n
        self.dfdp_he = b.dfdp * self.he
        phi = np.radians(phi_set_deg)
        # reference frame: setpoint phasor is real-positive; beam phasor at
        # phi_s relative to crest -> decelerating projection cos(phi_s)
        v_ref = v_set.astype(complex)
        # steady-state feedforward drive (holds field with beam if gated)
        i_dc = i_beam_ma * 1e-3 * duty_keep if beam_on else 0.0
        ib_full = -2.0 * i_dc * np.exp(-1j * phi) * 1e-6  # MA -> MV units via RL later
        # (Ib in amps; RL in ohms gives volts -> convert to MV: *1e-6)
        vfor_nobeam = 0.5 * v_ref                       # V = 2*Vfor at resonance
        vfor_beam = 0.5 * (v_ref - b.rl * ib_full * 1e6 * 1e-6)
        # SSA saturation limit: absolute amplifier rating
        vfor_max = self.vfor_ssa + 1e-9

        err_hist = [np.zeros(n, dtype=complex)] * (LOOP_DELAY + 1)
        beam_i0 = int(0.0 / DT)
        beam_i1 = int(BEAM_S / DT)

        # quench dynamics: effective bandwidth blows up as Q0 collapses
        w12_eff_base = b.w12.copy()

        # inter-pulse gap (49.45 ms >> tau): the CW loop (closed-loop BW
        # ~86 kHz >> any microphonic line) has the field regulated at the
        # setpoint by pulse start; only unpowered cavities sit at their
        # open-loop steady state (~0)
        w12_loss0 = w12_eff_base * self.q0_fac
        dw0 = 2 * np.pi * self.detuning_now(0.0)
        vss0 = (w12_eff_base * 2.0 * np.where(tripped, 0.0, vfor_nobeam)) \
            / (w12_loss0 - 1j * dw0)
        off = tripped | self.quenched
        self.Vc = np.where(off, vss0, v_ref)
        self.int_err[:] = 0.0

        amps = np.zeros((NSTEP, len(want_wf))) if want_wf else None
        phs = np.zeros((NSTEP, len(want_wf))) if want_wf else None
        fwd = np.zeros((NSTEP, len(want_wf))) if want_wf else None
        det_tr = np.zeros((NSTEP, len(want_wf))) if want_wf else None

        sum_v = np.zeros(n, dtype=complex)
        max_pf = np.zeros(n)
        sum_det = np.zeros(n)

        e_acc = np.abs(self.Vc) / b.leff  # MV/m at window start
        for k in range(NSTEP):
            t = k * DT
            beam_gate = beam_i0 <= k < beam_i1
            det = self.detuning_now(t)
            for m, (fm, qm, _sh) in enumerate(MECH_MODES):
                wm = 2 * np.pi * fm
                det = det + self.ring_amp[m] * np.exp(-wm / (2 * qm) * t) \
                    * np.sin(wm * t + self.ring_ph[m])
            dw = 2 * np.pi * det

            # LLRF PI with loop delay + gated feedforward
            err = v_ref - self.Vc
            err_hist.append(err)
            e_d = err_hist.pop(0)
            vff = vfor_beam if beam_gate else vfor_nobeam
            vfor = vff + 0.5 * (self.gp * e_d + self.ki * self.int_err)
            # SSA saturation (with integrator anti-windup) + trips = RF off
            mag = np.abs(vfor)
            over = mag > vfor_max
            self.int_err += np.where(over | tripped, 0.0, e_d) * DT
            vfor = np.where(over, vfor * (vfor_max / np.maximum(mag, 1e-12)),
                            vfor)
            vfor = np.where(tripped, 0.0, vfor)

            ib = ib_full if beam_gate else 0.0
            # quench: dissipation term grows (Q0 collapse); coupler drive
            # coupling stays fixed -> the field collapses toward 2Vfor/q0fac
            w12_loss = w12_eff_base * self.q0_fac
            itot = 2.0 * vfor + b.rl * ib * np.where(tripped, 0, 1)
            a = np.exp((-w12_loss + 1j * dw) * DT)
            vss = (w12_eff_base * itot) / (w12_loss - 1j * dw)
            self.Vc = a * self.Vc + (1.0 - a) * vss
            e_acc = np.abs(self.Vc) / b.leff

            sum_v += self.Vc
            sum_det += det
            # P_for = |Vfor|^2 / ((r/Q) Q_L) = |Vfor[V]|^2 / (2 R_L)  [W]
            pf = (np.abs(vfor) * 1e6) ** 2 / (2.0 * b.rl)
            max_pf = np.maximum(max_pf, pf)
            if want_wf:
                amps[k] = np.abs(self.Vc[want_wf])
                phs[k] = np.degrees(np.angle(self.Vc[want_wf]))
                fwd[k] = pf[want_wf] * 1e-3
                det_tr[k] = det[want_wf]

        # static LFD follows E^2 with a mechanical settling lag; gradient
        # TRANSIENTS (trips, quenches, recovery ramps) kick decaying rings —
        # the ~10% of the kick the piezo feedforward cannot cancel
        e2 = e_acc ** 2
        target = -b.kl * e2
        self.lfd_slow += (target - self.lfd_slow) * min(
            self.tick_dt / 0.2, 1.0)
        kick = np.abs(b.kl * (e2 - self._e2_prev)) * (1.0 - LFD_COMP)
        for m, (_f, _q, share) in enumerate(MECH_MODES):
            self.ring_amp[m] = np.minimum(
                self.ring_amp[m] + share * kick, 500.0)
        self._e2_prev = e2
        # tuner stack: piezo feedback nulls mean detuning pulse-to-pulse
        # (usable BW ~20 Hz, 0.5 Hz resolution) while the slow stepper takes
        # the long-term load; without the piezo a detuning death-spiral
        # develops as LFD follows any field sag faster than a 30 s stepper
        mean_det = sum_det / NSTEP
        self.tuner += 0.5 * mean_det + mean_det * (self.tick_dt / 30.0)
        self.tuner = np.round(self.tuner / 0.5) * 0.5   # piezo resolution
        self.t += self.tick_dt

        mean_v = sum_v / NSTEP
        return {
            "amp": np.abs(mean_v),
            "phase_err": np.degrees(np.angle(mean_v / (v_ref + 1e-12))),
            "detuning": mean_det,
            "p_for": max_pf,             # W
            "wf": (amps, phs, fwd, det_tr) if want_wf else None,
        }

    # ------------------------------------------------------------ quench

    def start_quench(self, idx: np.ndarray):
        """Q0 collapse: bandwidth grows x200 -> field dies within ~0.2 ms."""
        self.quenched[idx] = True
        self.q0_fac[idx] = 200.0

    def clear_quench(self, idx, v_set=None):
        self.quenched[idx] = False
        self.q0_fac[idx] = 1.0
        self.Vc[idx] = 0.0
        self.int_err[idx] = 0.0
        if v_set is not None:   # recovery ramp re-tunes the cavity
            e2 = (np.asarray(v_set) / self.bank.leff[idx]) ** 2
            self.lfd_slow[idx] = -self.bank.kl[idx] * e2
            self.tuner[idx] = self.lfd_slow[idx]
            self._e2_prev[idx] = e2
