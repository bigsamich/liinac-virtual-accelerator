"""Autotune service: puts the machine back on its feet and keeps it there.

Two functions, driven by the settings:autotune:main hash:

* restore=1 (one-shot "rescue"): clears injected faults, resets tripped
  devices, and slews every magnet/RF setpoint back to lattice design values.
  Clears itself when everything is back within tolerance.

* enable=1 (continuous orbit trim): SVD orbit correction. At startup the
  service measures its own orbit response matrix by kicking each corrector in
  the envelope engine (model-based, like an ORM measured on the real machine),
  then every couple of seconds solves min ||x + R dI|| and applies a damped
  correction to the corrector setpoints.

All setpoint writes go through the settings audit log with source=autotune.
"""
from __future__ import annotations

import json
import logging

import numpy as np

from pip2va.common import audit, codec, keys
from pip2va.physics.envelope import EnvelopeEngine
from pip2va.services.base import Service, main_for

log = logging.getLogger(__name__)

CADENCE = 40          # pulses between correction steps (2 s at 20 Hz)
GAIN = 0.4            # damped correction gain
MAX_CORR_A = 10.0     # corrector supply limit
RESTORE_FRAC = 0.10   # per-step fraction of remaining distance to design


class AutotuneService(Service):
    name = "autotune"

    def on_start(self):
        self.cadence = CADENCE
        self.engine = EnvelopeEngine(self.lat)
        self.correctors = [e for e in self.lat.elements if e.type == "corrector"]
        self.magnets = [e for e in self.lat.elements
                        if e.type in ("solenoid", "quad")]
        self.cavities = [e for e in self.lat.elements
                         if e.type in ("rfgap", "rfq")]
        self.r.hsetnx(keys.settings("autotune", "main"), "enable", 0)
        self.r.hsetnx(keys.settings("autotune", "main"), "restore", 0)
        self._resp = self._measure_response()
        # Tikhonov-regularized inverse: filter factors s/(s^2 + lam^2) damp
        # the weak singular directions that otherwise dump huge strength into
        # a handful of correctors while the rest idle.
        u, s, vt = np.linalg.svd(self._resp, full_matrices=False)
        lam = 0.15 * s.max()
        self._pinv = (vt.T * (s / (s ** 2 + lam ** 2))) @ u.T
        self.r.hset("state:autotune", mapping={
            "status": "idle", "orbit_rms_um": -1.0})
        log.info("response matrix %s, pinv ready", self._resp.shape)

    # ---------------------------------------------------- response matrix

    def _measure_response(self) -> np.ndarray:
        """Model ORM: BPM (x then y) response to +1 A on each corrector knob."""
        base = self.engine.run({})
        ref = np.concatenate([base.bpm_x, base.bpm_y])
        cols = []
        for el in self.correctors:
            for fld in ("current_x", "current_y"):
                res = self.engine.run({el.name: {fld: 1.0}})
                cols.append(np.concatenate([res.bpm_x, res.bpm_y]) - ref)
        return np.array(cols).T   # (2*nbpm, 2*ncorr)

    # ------------------------------------------------------------- ticking

    def on_tick(self, pulse_id: int):
        if pulse_id % self.cadence:
            return
        st = self.read_hash(keys.settings("autotune", "main"))
        if st.get("restore"):
            self._restore_step()
        elif st.get("enable"):
            self._orbit_step()
        else:
            self.r.hset("state:autotune", "status", "idle")

    # ------------------------------------------------------------- restore

    def _restore_step(self):
        self.r.hset("state:autotune", "status", "restoring")
        remaining = 0.0
        tripped_left = 0
        # 1. clear injected faults
        for k in self.r.scan_iter("fault:*"):
            self.r.delete(k)
        pipe = self.r.pipeline(transaction=False)
        # 2. reset tripped devices, slew setpoints toward design
        for el in self.magnets:
            skey = keys.settings("magnet", el.name)
            cur = float(self.read_hash(skey).get(
                "current", el.params["design_current"]))
            tgt = el.params["design_current"]
            if self.read_hash(keys.readback("magnet", el.name)).get(
                    "status") == "tripped":
                tripped_left += 1
                pipe.hset(skey, "reset", 1)
            step = (tgt - cur) * RESTORE_FRAC if abs(tgt - cur) > 1e-3 else 0.0
            if step:
                remaining = max(remaining, abs(tgt - cur - step) / max(abs(tgt), 1.0))
                pipe.hset(skey, "current", cur + step)
                audit.log_setting(self.r, skey, "current", cur + step, "autotune")
        for el in self.correctors:
            skey = keys.settings("magnet", el.name)
            h = self.read_hash(skey)
            for fld in ("current_x", "current_y"):
                cur = float(h.get(fld, 0.0))
                if abs(cur) > 0.01:
                    remaining = max(remaining, abs(cur) * 0.01)
                    pipe.hset(skey, fld, cur * (1.0 - 2 * RESTORE_FRAC))
                    audit.log_setting(self.r, skey, fld,
                                      cur * (1.0 - 2 * RESTORE_FRAC), "autotune")
        for el in self.cavities:
            skey = keys.settings("rf", el.name)
            p = el.params
            tgt_a = p.get("v_mv", p.get("v_design", 1.0))
            tgt_p = p.get("phi_deg", 0.0)
            h = self.read_hash(skey)
            if self.read_hash(keys.readback("rf", el.name)).get(
                    "status") == "tripped":
                tripped_left += 1
                pipe.hset(skey, "reset", 1)
            for fld, tgt in (("amp", tgt_a), ("phase", tgt_p)):
                cur = float(h.get(fld, tgt))
                if abs(tgt - cur) > 1e-4 * max(abs(tgt), 1.0):
                    remaining = max(remaining,
                                    abs(tgt - cur) / max(abs(tgt), 1.0))
                    pipe.hset(skey, fld, cur + (tgt - cur) * 2 * RESTORE_FRAC)
                    audit.log_setting(self.r, skey, fld,
                                      cur + (tgt - cur) * 2 * RESTORE_FRAC,
                                      "autotune")
        pipe.execute()
        self.publish_event(keys.CH_SETTINGS, {"key": "bulk:autotune"})
        if remaining >= 0.002 or tripped_left:
            self.r.hset("state:autotune", "status",
                        f"restoring ({tripped_left} devices still tripped)"
                        if tripped_left else "restoring")
            return
        # setpoints at design and nothing tripped: bring the permit back and
        # only declare success once the beam is actually being delivered
        beam = self.read_hash("state:beam")
        permit_on = self.r.get("state:mps.permit") in (b"1", "1")
        if not permit_on:
            self.r.hset(keys.settings("mps", "main"), "reset", 1)
            self.r.hset("state:autotune", "status", "restoring (permit reset)")
            return
        if beam.get("transmission", 0.0) < 0.9:
            self.r.hset("state:autotune", "status", "restoring (waiting beam)")
            return
        self.r.hset(keys.settings("autotune", "main"), "restore", 0)
        self.r.hset("state:autotune", "status", "idle")
        self.r.xadd(keys.stream("mps.events"),
                    {"t": __import__("time").time(), "kind": "autotune",
                     "detail": "restore-to-design complete"},
                    maxlen=500, approximate=True)

    # ------------------------------------------------------- orbit correct

    def _orbit_step(self):
        beam = self.read_hash("state:beam")
        if not beam or beam.get("transmission", 0.0) < 0.5:
            self.r.hset("state:autotune", "status", "waiting for beam")
            return
        entries = self.r.xrevrange(keys.stream("bpm.orbit"), count=10)
        if not entries:
            return
        xs, ys = [], []
        for _, fields in entries:
            _, d = codec.unpack(fields[b"d"])
            xs.append(d["x"])
            ys.append(d["y"])
        meas = np.concatenate([np.mean(xs, axis=0), np.mean(ys, axis=0)])
        rms_um = float(np.sqrt(np.mean(meas ** 2)) * 1e6)
        d_i = -GAIN * (self._pinv @ meas)
        pipe = self.r.pipeline(transaction=False)
        k = 0
        for el in self.correctors:
            skey = keys.settings("magnet", el.name)
            h = self.read_hash(skey)
            for fld in ("current_x", "current_y"):
                new = float(np.clip(float(h.get(fld, 0.0)) + d_i[k],
                                    -MAX_CORR_A, MAX_CORR_A))
                pipe.hset(skey, fld, new)
                audit.log_setting(self.r, skey, fld, new, "autotune")
                k += 1
        pipe.execute()
        self.publish_event(keys.CH_SETTINGS, {"key": "bulk:autotune"})
        self.r.hset("state:autotune", mapping={
            "status": "orbit trim active", "orbit_rms_um": rms_um})


if __name__ == "__main__":
    main_for(AutotuneService)
