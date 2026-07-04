"""RF system simulator: one LLRF-controlled cavity per rfgap/rfq element.

Models per cavity: amplitude servo (fast first-order), phase set + jitter,
detuning = microphonics (3-tone + noise) + Lorentz-force detuning pulled back
by a slow tuner servo, forward-power estimate, quench/trip latch with
explicit-reset semantics, and fault injection (trip / detune).
"""
from __future__ import annotations

import json
import math

import numpy as np

from pip2va.common import keys
from pip2va.common.devmodel import FirstOrderDevice
from pip2va.services.base import Service, main_for

MICRO_TONES = ((11.7, 3.0), (27.3, 2.0), (46.1, 1.2))  # (Hz, Hz-amplitude)


class Cavity:
    def __init__(self, el, rng):
        self.el = el
        p = el.params
        self.is_rfq = el.type == "rfq"
        self.v_design = p.get("v_mv", p.get("v_design", 1.0))
        self.quench = p.get("quench_mv", 1.3 * self.v_design)
        self.half_bw = p.get("half_bw_hz", 40.0)
        self.phi_design = p.get("phi_deg", 0.0)
        self.v_max = p.get("v_max_mv", self.v_design)
        self.amp = FirstOrderDevice(self.v_design, 0.15, 6e-4, 0.0, rng)
        self.phase_set = self.phi_design
        self.lfd_comp = 0.9          # piezo compensates 90% of static LFD
        self.tuner_offset = 0.0      # slow tuner state [Hz]
        self.det_drift = 0.0
        self.phases = rng.uniform(0, 2 * math.pi, size=len(MICRO_TONES))
        self.rng = rng

    def detuning(self, t: float, dt: float) -> float:
        micro = sum(a * math.sin(2 * math.pi * f * t + p)
                    for (f, a), p in zip(MICRO_TONES, self.phases))
        micro += self.rng.normal(0.0, 0.8)
        lfd = -20.0 * (self.amp.value / max(self.v_max, 1e-9)) ** 2
        self.det_drift += self.rng.normal(0.0, 0.02) - self.det_drift * dt / 600.0
        raw = micro + lfd * (1.0 - self.lfd_comp) + self.det_drift * 60.0
        # slow tuner servo nulls the mean detuning (time constant ~30 s)
        self.tuner_offset += (raw - self.tuner_offset) * dt / 30.0
        return raw - self.tuner_offset


class RfSimService(Service):
    name = "rf-sim"
    extra_channels = (keys.CH_SETTINGS,)

    def on_start(self):
        rng = np.random.default_rng(1962)
        self.dt = 1.0 / self.settings.tick_hz
        self.cavs: list[Cavity] = []
        for el in self.lat.elements:
            if el.type not in ("rfgap", "rfq"):
                continue
            cav = Cavity(el, rng)
            skey = keys.settings("rf", el.name)
            self.r.hsetnx(skey, "amp", cav.v_design)
            self.r.hsetnx(skey, "phase", cav.phi_design)
            self.cavs.append(cav)
        self.r.set("lattice:rf.index",
                   json.dumps([c.el.name for c in self.cavs]))
        self._dirty = {keys.settings("rf", c.el.name) for c in self.cavs}

    def on_event(self, channel, data):
        if isinstance(data, dict) and "key" in data:
            self._dirty.add(data["key"])

    def on_tick(self, pulse_id: int):
        t = pulse_id * self.dt
        n = len(self.cavs)
        amp = np.zeros(n, dtype=np.float32)
        phase = np.zeros(n, dtype=np.float32)
        det = np.zeros(n, dtype=np.float32)
        stat = np.zeros(n, dtype=np.float32)
        fwd = np.zeros(n, dtype=np.float32)
        pipe = self.r.pipeline(transaction=False)
        for i, cav in enumerate(self.cavs):
            el = cav.el
            skey = keys.settings("rf", el.name)
            rkey = keys.readback("rf", el.name)
            if skey in self._dirty:
                st = self.read_hash(skey)
                cav.amp.setpoint = float(st.get("amp", cav.amp.setpoint))
                cav.phase_set = float(st.get("phase", cav.phase_set))
                if cav.amp.tripped and st.get("reset"):
                    fkey = keys.fault("rf", el.name)
                    if cav.amp.setpoint <= cav.quench and not self.r.exists(fkey):
                        cav.amp.try_reset()
                        cav.amp.value = 0.0  # re-fill from zero
                    pipe.hdel(skey, "reset")
                self._dirty.discard(skey)
            # quench on excessive setpoint or injected fault
            fkey = keys.fault("rf", el.name)
            fl = self.read_hash(fkey) if self.r.exists(fkey) else {}
            if not cav.amp.tripped and (cav.amp.setpoint > cav.quench
                                        or fl.get("type") == "trip"):
                cav.amp.trip()
                self.publish_event(keys.CH_FAULT, {"key": rkey})
            d = cav.detuning(t, self.dt)
            if fl.get("type") == "detune":
                d += float(fl.get("magnitude", 0.0))
            a = cav.amp.step(self.dt)
            # residual phase error from detuning under closed-loop LLRF
            ph = (cav.phase_set
                  + math.degrees(math.atan2(d, cav.half_bw)) * 0.02
                  + cav.rng.normal(0.0, 0.06))
            p_fwd = (a / max(cav.v_max, 1e-9)) ** 2 * (1.0 + (d / cav.half_bw) ** 2)
            amp[i], phase[i], det[i] = a, ph, d
            stat[i] = 1.0 if cav.amp.tripped else 0.0
            fwd[i] = p_fwd
            pipe.hset(rkey, mapping={
                "amp": float(a), "phase": float(ph), "detuning_hz": float(d),
                "forward_pw": float(p_fwd),
                "status": "tripped" if cav.amp.tripped else "ok"})
        pipe.execute()
        self.publish_stream("rf.cavity", pulse_id, {
            "amp": amp, "phase": phase, "detuning_hz": det,
            "status": stat, "forward_pw": fwd})


if __name__ == "__main__":
    main_for(RfSimService)
