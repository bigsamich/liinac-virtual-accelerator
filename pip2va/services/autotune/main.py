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
        # correctors with almost no downstream lever arm (e.g. the last one
        # before the dump) have near-degenerate response columns: the solver
        # winds them up chasing noise. Freeze them out.
        col = np.linalg.norm(self._resp, axis=0)
        self._weak = col < 0.1 * np.median(col)
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
        if self.r.hget("state:study", "run") == b"1":
            self._study_step()
        elif st.get("restore"):
            self._restore_step()
        elif st.get("bba"):
            self._bba_step()
        elif st.get("enable"):
            self._orbit_step()
        else:
            self.r.hset("state:autotune", "status", "idle")

    # ----------------------------------------------------------- studies

    def _study_step(self):
        """Execute one cadence of the active beam study (plan in
        state:study.plan): apply the step's setpoints, dwell, capture
        instrumentation, abort+restore on MPS trip."""
        import json as _json
        import time as _time
        if not hasattr(self, "_study"):
            try:
                plan = _json.loads(self.r.hget("state:study", "plan"))
            except (TypeError, ValueError):
                self.r.hset("state:study", "run", 0)
                return
            originals = []
            for sw in plan["sweeps"]:
                skey = keys.settings(sw["cls"], sw["device"])
                originals.append(float(self.read_hash(skey).get(
                    sw["field"], sw["from"])))
            self._study = {"plan": plan, "orig": originals, "k": -1,
                           "dwell_left": 0, "steps": [], "grace": 15}
            self.r.hset("state:study", mapping={
                "status": "running", "step": 0,
                "total": plan["steps"]})
        stu = self._study
        plan = stu["plan"]

        def apply(values):
            for sw, v in zip(plan["sweeps"], values):
                skey = keys.settings(sw["cls"], sw["device"])
                self.r.hset(skey, sw["field"], float(v))
                audit.log_setting(self.r, skey, sw["field"], float(v),
                                  f"study:{plan['name']}")
                self.publish_event(keys.CH_SETTINGS, {"key": skey})

        def finish(status):
            if plan.get("restore", True) or status != "completed":
                apply(stu["orig"])
            self.r.hset("state:study", mapping={
                "run": 0, "status": status,
                "result": _json.dumps({"status": status,
                                       "steps": stu["steps"],
                                       "t_end": _time.time()})})
            self.r.xadd(keys.stream("mps.events"),
                        {"t": _time.time(), "kind": "study",
                         "detail": f"{plan['name']}: {status} "
                                   f"({len(stu['steps'])} steps)"},
                        maxlen=500, approximate=True)
            del self._study

        # arm the beam first (studies need beam); abort only on a trip
        # that happens DURING the scan
        permit_on = self.r.get("state:mps.permit") in (b"1", "1")
        if stu["k"] < 0 and not permit_on:
            if stu["grace"] <= 0:
                finish("aborted-no-beam")
                return
            stu["grace"] -= 1
            self.r.hset(keys.settings("mps", "main"), "reset", 1)
            self.r.hset("state:study", "status", "arming beam")
            return
        if stu["k"] >= 0 and not permit_on:
            finish("aborted-trip")   # empirical limit found mid-scan
            return

        if stu["dwell_left"] > 0:
            stu["dwell_left"] -= 1
            return
        # intensity-ramp mode: re-baseline the MPS at each plateau so the
        # loss pattern of the new current becomes the reference
        if plan.get("rebaseline") and stu.get("await_arm"):
            armed = any(f.get(b"kind") == b"armed"
                        and float(f.get(b"t", 0)) > stu["await_arm"]
                        for _, f in self.r.xrevrange(
                            keys.stream("mps.events"), count=5))
            if not armed:
                stu["await_arm_n"] = stu.get("await_arm_n", 0) + 1
                if stu["await_arm_n"] > 60:
                    finish("aborted-rebaseline")
                return
            stu["await_arm"] = None
        # capture the completed step (after its dwell)
        if stu["k"] >= 0:
            stu["steps"].append(self._study_capture(plan, stu["k"]))
            self.r.hset("state:study", "step", stu["k"] + 1)
        stu["k"] += 1
        if stu["k"] >= plan["steps"]:
            finish("completed")
            return
        frac = stu["k"] / max(plan["steps"] - 1, 1)
        values = [sw["from"] + (sw["to"] - sw["from"]) * frac
                  for sw in plan["sweeps"]]
        apply(values)
        stu["values"] = values
        stu["dwell_left"] = max(
            1, int(plan["dwell_s"] * self.settings.tick_hz / self.cadence))
        if plan.get("rebaseline"):
            import time as _t
            self.r.hset(keys.settings("mps", "main"), "relearn", 1)
            self.r.hset(keys.settings("mps", "main"), "reset", 1)
            stu["await_arm"] = _t.time()
            stu["await_arm_n"] = 0

    def _study_capture(self, plan, k):
        n_avg = 10
        xs, ys, wt = [], [], []
        for _, f in self.r.xrevrange(keys.stream("bpm.orbit"), count=n_avg):
            _, d = codec.unpack(f[b"d"])
            xs.append(d["x"])
            ys.append(d["y"])
            if len(d.get("w_tof", [])):
                wt.append(float(d["w_tof"][-1]))
        wl = 0.0
        e = self.r.xrevrange(keys.stream("blm.losses"), count=n_avg)
        if e:
            wl = float(np.max([codec.unpack(f[b"d"])[1]["wpm"].max()
                               for _, f in e]))
        tor = 0.0
        e = self.r.xrevrange(keys.stream("toroid.current"), count=1)
        if e:
            tor = float(codec.unpack(e[0][1][b"d"])[1]["i_ma"][-1])
        beam = self.read_hash("state:beam")
        orbit = float(np.sqrt(np.mean(np.concatenate(
            [np.mean(xs, axis=0), np.mean(ys, axis=0)]) ** 2)) * 1e3)             if xs else 0.0
        return {"step": k + 1,
                "set_values": [float(v) for v in
                               self._study.get("values",
                                               [0] * len(plan["sweeps"]))],
                "transmission": float(beam.get("transmission", 0.0)),
                "w_tof": float(np.mean(wt)) if wt else 0.0,
                "worst_blm": wl, "i_out_ma": tor,
                "orbit_rms_mm": orbit}

    # -------------------------------------------------- beam-based alignment

    def _bba_targets(self):
        """(magnet, bpm) pairs: each BPM with the focusing magnet just
        upstream in the same package."""
        pairs = []
        els = self.lat.elements
        for i, e in enumerate(els):
            if e.type != "bpm":
                continue
            for j in range(i - 1, max(i - 5, -1), -1):
                if els[j].type in ("quad", "solenoid"):
                    pairs.append((els[j], e))
                    break
        return pairs

    def _bba_step(self):
        """Quad-shunt BBA, one magnet per call: measure the downstream
        orbit shift for a 5% shunt, project it on the model sensitivity
        column for a unit magnet offset, infer the true beam position at
        the magnet, and hence the BPM's electrical offset."""
        if not hasattr(self, "_bba"):
            self._bba = {"pairs": self._bba_targets(), "i": 0, "phase": 0,
                         "m0": None, "nominal": None}
        bb = self._bba
        if bb["i"] >= len(bb["pairs"]):
            self.r.hset(keys.settings("autotune", "main"), "bba", 0)
            self.r.hset("state:autotune", "status",
                        f"BBA complete: {len(bb['pairs'])} BPMs calibrated")
            self.r.xadd(keys.stream("mps.events"),
                        {"t": __import__("time").time(), "kind": "bba",
                         "detail": f"{len(bb['pairs'])} BPM offsets learned"},
                        maxlen=500, approximate=True)
            del self._bba
            return
        mag, bpm = bb["pairs"][bb["i"]]
        skey = keys.settings("magnet", mag.name)
        # a shunt can push losses over threshold: restore, reset, resume
        if self.r.get("state:mps.permit") not in (b"1", "1"):
            if bb["phase"] > 0 and bb.get("nominal") is not None:
                self.r.hset(skey, "current", bb["nominal"])
                self.publish_event(keys.CH_SETTINGS, {"key": skey})
                bb["phase"] = 0
            self.r.hset(keys.settings("mps", "main"), "reset", 1)
            self.r.hset("state:autotune", "status",
                        f"BBA paused at {bpm.name} (permit trip; resuming)")
            return
        self.r.hset("state:autotune", "status",
                    f"BBA {bb['i'] + 1}/{len(bb['pairs'])}: {bpm.name}")

        def measure():
            xs, ys = [], []
            for _, f in self.r.xrevrange(keys.stream("bpm.orbit"), count=15):
                _, d = codec.unpack(f[b"d"])
                xs.append(d["x"])
                ys.append(d["y"])
            return (np.mean(xs, axis=0), np.mean(ys, axis=0)) if xs else None

        if bb["phase"] == 0:                      # baseline measurement
            m = measure()
            if m is None:
                return
            bb["m0"] = np.concatenate(m)
            bb["nominal"] = float(self.read_hash(skey).get(
                "current", mag.params["design_current"]))
            self.r.hset(skey, "current", bb["nominal"] * 1.05)
            audit.log_setting(self.r, skey, "current",
                              bb["nominal"] * 1.05, "bba")
            self.publish_event(keys.CH_SETTINGS, {"key": skey})
            bb["phase"] = 1
        elif bb["phase"] == 1:                    # settle one cadence
            bb["phase"] = 2
        else:                                     # shunted measurement
            m = measure()
            self.r.hset(skey, "current", bb["nominal"])
            audit.log_setting(self.r, skey, "current", bb["nominal"], "bba")
            self.publish_event(keys.CH_SETTINGS, {"key": skey})
            if m is not None:
                dmeas = np.concatenate(m) - bb["m0"]
                for plane, err_key in ((0, "dx"), (1, "dy")):
                    col = self._bba_column(mag, plane)
                    denom = float(col @ col)
                    if denom < 1e-18:
                        continue
                    x_true = float(dmeas @ col) / denom   # beam pos at magnet
                    bi = self._bpm_index(bpm.name)
                    meas0 = bb["m0"][bi + plane * self._nbpm]
                    self.r.hset("state:bba.offsets", f"{bpm.name}:{err_key}",
                                float(meas0 - x_true))
            bb["i"] += 1
            bb["phase"] = 0

    def _bpm_index(self, name):
        if not hasattr(self, "_bpm_pos"):
            bpms = self.lat.instruments("bpm")
            self._bpm_pos = {e.name: i for i, e in enumerate(bpms)}
            self._nbpm = len(bpms)
        return self._bpm_pos[name]

    def _bba_column(self, mag, plane):
        """Model sensitivity: d(orbit shift under 5% shunt)/d(beam offset
        at the magnet). Four engine runs, cached per magnet/plane."""
        if not hasattr(self, "_bba_cols"):
            self._bba_cols = {}
        key = (mag.name, plane)
        if key in self._bba_cols:
            return self._bba_cols[key]
        i0 = float(mag.params["design_current"])
        off = {"dx": 1e-3, "dy": 0.0} if plane == 0 else             {"dx": 0.0, "dy": 1e-3}
        eng_err = EnvelopeEngine(self.lat, errors={mag.name: off})
        base_n = self.engine.run({})
        base_s = self.engine.run({mag.name: {"current": i0 * 1.05}})
        err_n = eng_err.run({})
        err_s = eng_err.run({mag.name: {"current": i0 * 1.05}})

        def vec(r):
            return np.concatenate([r.bpm_x, r.bpm_y])

        col = ((vec(err_s) - vec(err_n)) - (vec(base_s) - vec(base_n))) / 1e-3
        self._bba_cols[key] = col
        return col

    # ------------------------------------------------------------- restore

    def _restore_step(self):
        """Cold-restart to a KNOWN state, verified phase by phase:
        0: beam off, faults cleared, ALL setpoints hard-set to design
           (correctors from golden only if its lattice fingerprint matches)
        1: wait until every readback has converged onto its setpoint
        2: re-baseline the MPS (relearn) and restore the permit
        3: verify beam delivery, then declare the machine restored."""
        import json as _json
        import time as _time
        from pip2va.common import snapshots as _snap
        if not hasattr(self, "_restore"):
            self._restore = {"phase": 0, "waited": 0}
        ph = self._restore

        if ph["phase"] == 0:
            self.r.set("state:mps.permit", 0)      # restore without beam
            for k in self.r.scan_iter("fault:*"):
                self.r.delete(k)
            golden = {}
            try:
                g = _snap.load("golden")
                if g.get("fingerprint") == _snap.fingerprint():
                    golden = g["settings"]
                else:
                    self.r.hset("state:autotune", "status",
                                "restore: golden ignored (stale lattice)")
            except (FileNotFoundError, OSError, ValueError, KeyError):
                pass
            pipe = self.r.pipeline(transaction=False)
            for el in self.magnets:
                skey = keys.settings("magnet", el.name)
                pipe.hset(skey, "current", el.params["design_current"])
                pipe.hset(skey, "reset", 1)
                audit.log_setting(self.r, skey, "current",
                                  el.params["design_current"], "restore")
            for el in self.correctors:
                skey = keys.settings("magnet", el.name)
                g = golden.get(skey, {})
                for fld in ("current_x", "current_y"):
                    pipe.hset(skey, fld, float(g.get(fld, 0.0)))
                pipe.hset(skey, "reset", 1)
            for el in self.cavities:
                skey = keys.settings("rf", el.name)
                p = el.params
                pipe.hset(skey, "amp", p.get("v_mv", p.get("v_design", 1.0)))
                pipe.hset(skey, "phase", p.get("phi_deg", 0.0))
                pipe.hset(skey, "reset", 1)
            pipe.hset(keys.settings("source", "main"), "current_ma",
                      self.lat.meta.get("peak_current_ma", 5.0))
            pipe.hset(keys.settings("chopper", "main"), "duty",
                      1.0 - self.lat.meta.get("chop_fraction", 0.6))
            pipe.execute()
            self.publish_event(keys.CH_SETTINGS, {"key": "bulk:restore"})
            self.r.hset("state:autotune", "status",
                        "restore 1/3: setpoints -> design, converging")
            ph["phase"], ph["waited"] = 1, 0
            return

        if ph["phase"] == 1:
            worst = 0.0
            for el in self.magnets:
                rb = self.read_hash(keys.readback("magnet", el.name))
                d = el.params["design_current"]
                try:
                    worst = max(worst, abs(float(rb.get("current", d)) - d)
                                / max(abs(d), 1.0))
                except (TypeError, ValueError):
                    pass
            ph["waited"] += 1
            if worst < 0.01 or ph["waited"] > 120:
                self.r.hset("state:autotune", "status",
                            f"restore 2/3: converged (dev {worst*100:.2f}%), "
                            "re-baselining MPS")
                if self.r.exists(keys.heartbeat("mps")):
                    self.r.hset(keys.settings("mps", "main"), "relearn", 1)
                    self.r.hset(keys.settings("mps", "main"), "reset", 1)
                    ph["t_arm"] = _time.time()
                    ph["phase"] = 2
                else:                       # unit tests: no MPS present
                    self.r.set("state:mps.permit", 1)
                    ph["phase"] = 3
                ph["waited"] = 0
            return

        if ph["phase"] == 2:
            ph["waited"] += 1
            armed = any(f.get(b"kind") == b"armed"
                        and float(f.get(b"t", 0)) > ph["t_arm"]
                        for _, f in self.r.xrevrange(
                            keys.stream("mps.events"), count=5))
            if ph["waited"] % 10 == 0:      # keep nudging the permit
                self.r.hset(keys.settings("mps", "main"), "reset", 1)
            if armed:
                ph["phase"], ph["waited"] = 3, 0
            elif ph["waited"] > 200:
                self._finish_restore("restore FAILED at MPS arming")
            return

        beam = self.read_hash("state:beam")
        ph["waited"] += 1
        if (self.r.get("state:mps.permit") in (b"1", "1")
                and beam.get("transmission", 0.0) > 0.9):
            self._finish_restore(
                f"RESTORED to known state (T={beam['transmission']:.3f})")
        elif ph["waited"] > 100:
            self._finish_restore("restore FAILED: beam not delivered")

    def _finish_restore(self, msg):
        import time as _time
        self.r.hset(keys.settings("autotune", "main"), "restore", 0)
        self.r.hset("state:autotune", "status", msg)
        self.r.xadd(keys.stream("mps.events"),
                    {"t": _time.time(), "kind": "autotune", "detail": msg},
                    maxlen=500, approximate=True)
        if hasattr(self, "_restore"):
            del self._restore

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
        # subtract BBA-learned electrical offsets: steer to magnetic centres
        raw = self.r.hgetall("state:bba.offsets")
        if raw:
            self._bpm_index(self.lat.instruments("bpm")[0].name)
            for k, v in raw.items():
                k = k.decode() if isinstance(k, bytes) else k
                name, plane = k.rsplit(":", 1)
                bi = self._bpm_pos.get(name)
                if bi is not None:
                    meas[bi + (0 if plane == "dx" else self._nbpm)] -= float(v)
        rms_um = float(np.sqrt(np.mean(meas ** 2)) * 1e6)
        if rms_um < 250.0:
            # at the BPM noise/offset floor: correcting further just random-
            # walks the trims until one rails (the BTL:C12 runaway). Hold,
            # but keep bleeding any frozen-out weak correctors toward zero.
            k = 0
            pipe = self.r.pipeline(transaction=False)
            for el in self.correctors:
                skey = keys.settings("magnet", el.name)
                h = None
                for fld in ("current_x", "current_y"):
                    if self._weak[k]:
                        h = h or self.read_hash(skey)
                        cur = float(h.get(fld, 0.0))
                        if abs(cur) > 0.05:
                            pipe.hset(skey, fld, cur * 0.85)
                    k += 1
            pipe.execute()
            self.publish_event(keys.CH_SETTINGS, {"key": "bulk:autotune"})
            self.r.hset("state:autotune", mapping={
                "status": "orbit trim: at noise floor (holding)",
                "orbit_rms_um": rms_um})
            return
        d_i = np.clip(-GAIN * (self._pinv @ meas), -0.3, 0.3)
        d_i[self._weak] = 0.0
        pipe = self.r.pipeline(transaction=False)
        k = 0
        for el in self.correctors:
            skey = keys.settings("magnet", el.name)
            h = self.read_hash(skey)
            for fld in ("current_x", "current_y"):
                cur = float(h.get(fld, 0.0))
                # leak toward zero (hard for frozen-out weak correctors):
                # bleeds any accumulated noise-walk
                leak = 0.90 if self._weak[k] else 0.995
                new = float(np.clip(cur * leak + d_i[k],
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
