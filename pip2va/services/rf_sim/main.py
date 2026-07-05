"""RF system simulator — physical SRF model (v4b).

Every 20 Hz tick integrates the complex cavity-envelope equation across the
0.55 ms pulse window for all cavities at once (see cavity_model.py): PI LLRF
with loop delay, gated beam loading + feedforward, stochastic microphonics,
Lorentz-force detuning with piezo compensation, physical quenches (Q0
collapse), CEBAF-style gradient-dependent stochastic trips, and explicit
reset semantics. Cavities selected in settings:wfsel:main (field "rf")
publish their intra-pulse waveforms to stream:wf.rf.
"""
from __future__ import annotations

import json
import math

import numpy as np

from pip2va.common import keys
from pip2va.services.base import Service, main_for

from .cavity_model import DT, NSTEP, CavityModel

# CEBAF-style stochastic trip law: ln(rate/hour) = A + B*G[MV/m]
TRIP_B = 0.9
TRIP_A = -12.63 - 6.10 * TRIP_B
PULSES_PER_HOUR = 72000.0


class RfSimService(Service):
    name = "rf-sim"
    extra_channels = (keys.CH_SETTINGS,)

    def on_start(self):
        self.rng = np.random.default_rng(1962)
        self.cavs = [e for e in self.lat.elements
                     if e.type in ("rfgap", "rfq")]
        n = len(self.cavs)
        self.model = CavityModel(self.cavs, self.rng,
                                 tick_dt=1.0 / self.settings.tick_hz)
        self.v_set = np.zeros(n)
        self.phi_set = np.zeros(n)
        self.quench_lim = np.array([
            c.params.get("quench_mv",
                         1.3 * c.params.get("v_mv", c.params.get("v_design", 1.0)))
            for c in self.cavs])
        self.tripped = np.zeros(n, dtype=bool)
        for j, el in enumerate(self.cavs):
            skey = keys.settings("rf", el.name)
            vd = el.params.get("v_mv", el.params.get("v_design", 1.0))
            pd = el.params.get("phi_deg", 0.0)
            self.r.hsetnx(skey, "amp", vd)
            self.r.hsetnx(skey, "phase", pd)
            st = self.read_hash(skey)
            self.v_set[j] = float(st.get("amp", vd))
            self.phi_set[j] = float(st.get("phase", pd))
        self.model.pretune(self.v_set)
        self.r.set("lattice:rf.index",
                   json.dumps([c.name for c in self.cavs]))
        self._pos = {c.name: j for j, c in enumerate(self.cavs)}
        self._dirty: set = set()
        self._t_wf = np.arange(NSTEP) * DT * 1e3   # ms axis
        # field-emission: per-cavity FN onset (E_acc where radiation ~1 unit)
        self._fe_onset = self.rng.uniform(1.2, 2.0, n) \
            * np.maximum(self.model.bank.v_max / self.model.bank.leff, 0.5)

    def on_event(self, channel, data):
        if isinstance(data, dict) and "key" in data:
            if str(data["key"]).startswith("bulk:"):
                self._dirty.update(keys.settings("rf", c.name)
                                   for c in self.cavs)
            else:
                self._dirty.add(data["key"])

    # ------------------------------------------------------------- per tick

    def _apply_settings(self):
        pipe = self.r.pipeline(transaction=False)
        for skey in list(self._dirty):
            self._dirty.discard(skey)
            name = skey.split(":", 2)[-1]
            j = self._pos.get(name)
            if j is None:
                continue
            st = self.read_hash(skey)
            self.v_set[j] = max(0.0, float(st.get("amp", self.v_set[j])))
            self.model.ff_frac[j] = float(np.clip(
                float(st.get("ff", self.model.ff_frac[j])), 0.0, 1.0))
            ph = float(st.get("phase", self.phi_set[j]))
            self.phi_set[j] = (ph + 180.0) % 360.0 - 180.0
            if st.get("reset") and self.tripped[j]:
                fkey = keys.fault("rf", name)
                if self.v_set[j] <= self.quench_lim[j] \
                        and not self.r.exists(fkey):
                    self.tripped[j] = False
                    self.model.clear_quench(np.array([j]), self.v_set[j])
                pipe.hdel(skey, "reset")
        pipe.execute()

    def _apply_faults(self):
        self.model.ext_det[:] = 0.0
        # cryo 2 K bath pressure -> detuning via family df/dp [Hz/mbar
        # class values; FAMILY table stores Hz/Torr, 1 Torr = 1.333 mbar]
        util = self.r.get("state:util")
        if util:
            try:
                u = json.loads(util)
                pm = u.get("p_mbar", {})
                self._lcw_c = float(u.get("lcw_c", 35.0))
                from pip2va.services.timing.utilities import (CRYOMODULES,
                                                              P_NOM_MBAR)
                for nm, sec, (a, b) in CRYOMODULES:
                    dp = pm.get(nm, P_NOM_MBAR) - P_NOM_MBAR
                    if abs(dp) < 1e-6:
                        continue
                    js = [j for j, c in enumerate(self.cavs)
                          if c.section == sec][a:b]
                    for j in js:
                        self.model.ext_det[j] += \
                            -(self.model.dfdp[j] / 1.333) * dp
            except (ValueError, KeyError):
                pass
        for k in self.r.scan_iter("fault:rf:*"):
            name = (k.decode() if isinstance(k, bytes) else k).split(":", 2)[-1]
            j = self._pos.get(name)
            if j is None:
                continue
            fl = self.read_hash(keys.fault("rf", name))
            if fl.get("type") == "trip" and not self.tripped[j]:
                self._trip(j)
            elif fl.get("type") == "detune":
                self.model.ext_det[j] = float(fl.get("magnitude", 0.0))

    def _trip(self, j: int):
        self.tripped[j] = True
        self.model.start_quench(np.array([j]))
        self.publish_event(keys.CH_FAULT,
                           {"key": keys.readback("rf", self.cavs[j].name)})

    def on_tick(self, pulse_id: int):
        self._apply_settings()
        self._apply_faults()
        m = self.model
        n = len(self.cavs)

        # quench conditions: over-limit setpoint, or stochastic (CEBAF law)
        e_acc = self.v_set / m.bank.leff
        over = (self.v_set > self.quench_lim) & ~self.tripped
        p_trip = np.exp(TRIP_A + TRIP_B * e_acc) / PULSES_PER_HOUR
        stoch = (self.rng.random(n) < p_trip) & ~self.tripped
        for j in np.nonzero(over | stoch)[0]:
            self._trip(int(j))

        permit = self.r.get("state:mps.permit")
        beam_on = permit is None or permit in (b"1", "1")
        chop = self.read_hash(keys.settings("chopper", "main"))
        duty = float(chop.get("duty",
                              1.0 - self.lat.meta.get("chop_fraction", 0.6)))
        src = self.read_hash(keys.settings("source", "main"))
        i_ma = float(src.get("current_ma",
                             self.lat.meta.get("peak_current_ma", 5.0)))

        # waveform selection
        sel = str(self.read_hash(keys.settings("wfsel", "main")).get("rf", ""))
        want = [self._pos[nm] for nm in sel.split(",") if nm in self._pos][:8]

        m.microphonics_step()
        res = m.run_window(self.v_set, self.phi_set, i_ma, beam_on, duty,
                           self.tripped, want_wf=want or None)

        amp = res["amp"] * (1 + self.rng.normal(0, 2e-4, n))
        phase = self.phi_set + res["phase_err"] \
            + self.rng.normal(0, 0.02, n)
        det = res["detuning"]
        fwd = res["p_for"] / 1e3   # kW
        stat = self.tripped.astype(np.float32)

        pipe = self.r.pipeline(transaction=False)
        for j, el in enumerate(self.cavs):
            pipe.hset(keys.readback("rf", el.name), mapping={
                "amp": float(amp[j]), "phase": float(phase[j]),
                "detuning_hz": float(det[j]),
                "forward_pw": float(fwd[j])
                * (1.0 - 0.004 * (getattr(self, "_lcw_c", 35.0) - 35.0)),
                "status": "tripped" if self.tripped[j] else "ok"})
        pipe.execute()
        # FN-like radiation signal: exponential in gradient above onset
        e_now = amp / self.model.bank.leff
        rad = np.exp(6.0 * (e_now / self._fe_onset - 1.0)).astype(np.float32)
        rad = np.where(e_now > 0.3 * self._fe_onset, rad, 0.0)
        self.publish_stream("rf.cavity", pulse_id, {
            "rad": rad,
            "amp": amp.astype(np.float32),
            "phase": phase.astype(np.float32),
            "detuning_hz": det.astype(np.float32),
            "status": stat, "forward_pw": fwd.astype(np.float32)})

        if want and res["wf"] is not None:
            amps, phs, fwds, dets = res["wf"]
            data = {"t_ms": self._t_wf.astype(np.float32)}
            for col, j in enumerate(want):
                nm = self.cavs[j].name
                data[f"{nm}:amp"] = amps[:, col].astype(np.float32)
                data[f"{nm}:phase"] = phs[:, col].astype(np.float32)
                data[f"{nm}:fwd_kw"] = fwds[:, col].astype(np.float32)
                data[f"{nm}:det"] = dets[:, col].astype(np.float32)
            self.publish_stream("wf.rf", pulse_id, data)


if __name__ == "__main__":
    main_for(RfSimService)
