"""beam-physics service — the simulation core.

Every pulse.tick: bulk-reads all device readbacks into a DeviceState snapshot,
runs the envelope engine, and writes ground truth (truth:beam) plus a summary
(state:beam). A daemon thread free-runs the GPU macroparticle tracker on the
latest snapshot and publishes stream:beam.deep after each full pass.

The GUI never reads truth:beam — diag-sim turns it into noisy measurements.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import numpy as np

from pip2va.common import codec, keys
from pip2va.common.lattice import load_errors
from pip2va.physics.envelope import EnvelopeEngine
from pip2va.physics.macro import MacroTracker
from pip2va.services.base import Service, main_for

log = logging.getLogger(__name__)


class BeamPhysicsService(Service):
    name = "beam-physics"

    def __init__(self, redis_client=None, settings=None, macro: bool = True,
                 errant_rate_per_pulse: float = 1.0 / 6000.0):
        super().__init__(redis_client=redis_client, settings=settings)
        self._macro_enabled = macro
        self._errant_rate = errant_rate_per_pulse
        self._errant_left = 0
        self._errant_kick = 0.0
        import numpy as _np
        self._rng = _np.random.default_rng(77)

    def on_start(self):
        self._errors = load_errors()
        if self._errors:
            log.info("as-built machine: %d element imperfections",
                     len(self._errors))
        self.engine = EnvelopeEngine(self.lat, errors=self._errors)
        self._prev_ds: dict = {}
        self._latest = {"ds": {}, "beam_on": True, "pulse_id": 0}
        self._rb_keys = []
        for el in self.lat.elements:
            if el.type in ("solenoid", "quad", "corrector"):
                self._rb_keys.append((el.name, keys.readback("magnet", el.name)))
            elif el.type in ("rfgap", "rfq"):
                self._rb_keys.append((el.name, keys.readback("rf", el.name)))
        if self._macro_enabled:
            self._macro_thread = threading.Thread(
                target=self._macro_loop, daemon=True)
            self._macro_thread.start()

    # ------------------------------------------------------------- per tick

    def _collect_device_state(self) -> tuple[dict, bool]:
        pipe = self.r.pipeline(transaction=False)
        for _, rk in self._rb_keys:
            pipe.hgetall(rk)
        pipe.hgetall(keys.settings("source", "main"))
        pipe.hgetall(keys.settings("chopper", "main"))
        scraper_keys = [e.name for e in self.lat.elements
                        if e.type == "scraper2"]
        for nm in scraper_keys:
            pipe.hgetall(keys.settings("scraper", nm))
        raw = pipe.execute()
        scraper_raw = raw[-len(scraper_keys):] if scraper_keys else []
        raw = raw[:len(raw) - len(scraper_keys)]
        scraper_ds = {}
        for nm, h in zip(scraper_keys, scraper_raw):
            if h:
                d = {}
                for k, v in h.items():
                    kk = k.decode() if isinstance(k, bytes) else k
                    vv = v.decode() if isinstance(v, bytes) else v
                    try:
                        d[kk] = float(vv)
                    except ValueError:
                        d[kk] = vv
                scraper_ds[nm] = d
        ds: dict = {}
        ds.update(scraper_ds)
        stale = False
        for (name, _), h in zip(self._rb_keys, raw[:-2]):
            if h:
                ds[name] = {
                    (k.decode() if isinstance(k, bytes) else k):
                    self._coerce(v) for k, v in h.items()}
            elif name in self._prev_ds:
                ds[name] = self._prev_ds[name]
                stale = True
            else:
                stale = True  # cold start: engine falls back to design values
        for key, h in zip(("LEBT:SRC", "MEBT:CHOP1"), raw[-2:]):
            if h:
                ds[key] = {
                    (k.decode() if isinstance(k, bytes) else k):
                    self._coerce(v) for k, v in h.items()}
        self._prev_ds = ds
        return ds, stale

    @staticmethod
    def _coerce(v):
        v = v.decode() if isinstance(v, bytes) else v
        try:
            return float(v)
        except (TypeError, ValueError):
            return v

    def on_tick(self, pulse_id: int):
        t0 = time.perf_counter()
        phys = self.read_hash(keys.settings("physics", "main"))
        for k, v in phys.items():
            if isinstance(v, float) and k in self.engine.phys:
                self.engine.phys[k] = v
        ds, stale = self._collect_device_state()
        permit = self.r.get("state:mps.permit")
        beam_on = permit is None or permit in (b"1", "1")
        # ---- dual-source legs: each source behaves slightly differently.
        # Leg A (ISRC:0110): reference. Leg B (ISRC:0120): -2.5% current
        # calibration, 6% larger emittance, 1.6x glitch rate. A changeover
        # drops the beam for ~3 s (real switching transient).
        leg = str(ds.get("LEBT:SRC", {}).get("leg", "A")).upper()
        if leg != getattr(self, "_leg", "A"):
            self._leg = leg
            self._leg_switch_t = time.time()
            self.r.xadd(keys.stream("mps.events"),
                        {"t": time.time(), "kind": "source",
                         "detail": f"source changeover -> leg {leg} "
                                   f"(ISRC:{'0110' if leg == 'A' else '0120'})"},
                        maxlen=500, approximate=True)
        if time.time() - getattr(self, "_leg_switch_t", 0.0) < 3.0:
            beam_on = False
        if leg == "B" and "LEBT:SRC" in ds:
            src = dict(ds["LEBT:SRC"])
            src["current_ma"] = float(src.get("current_ma", 5.0)) * 0.975
            ds = dict(ds)
            ds["LEBT:SRC"] = src
        self.engine.emit_scale = 1.06 if leg == "B" else 1.0
        # errant-beam events: a source/LEBT glitch mis-steers 2-3 pulses
        # (PIP2IT-style; the MPS race is to catch it)
        kick = 0.0
        if beam_on:
            if self._errant_left > 0:
                self._errant_left -= 1
                kick = self._errant_kick
            elif self._rng.random() < self._errant_rate * (
                    1.6 if getattr(self, '_leg', 'A') == 'B' else 1.0) * (
                    self._glitch_fault()):
                self._errant_left = int(self._rng.integers(2, 4))
                self._errant_kick = float(self._rng.choice([-1, 1])
                                          * self._rng.uniform(2.0, 5.0))
                kick = self._errant_kick
                self.r.xadd(keys.stream("mps.events"),
                            {"t": time.time(), "kind": "errant",
                             "detail": f"source glitch {kick:+.1f} mrad "
                                       f"x{self._errant_left + 1} pulses"},
                            maxlen=500, approximate=True)
        if pulse_id % 20 == 0:
            vb = self.r.get("state:vacuum.by_section")
            if vb:
                try:
                    self.engine.phys["pressure_by_section"] = \
                        {k: float(v) for k, v in json.loads(vb).items()}
                except ValueError:
                    pass
        res = self.engine.run(ds, beam_on=beam_on, errant_kick_mrad=kick)
        self._latest = {"ds": ds, "beam_on": beam_on, "pulse_id": pulse_id}
        if not hasattr(self, "_wcm_js"):
            # RWCM locations: MEBT exit (post-chopper) and BTL entrance
            s_arr = res.s
            self._wcm_js = [int(np.argmin(np.abs(s_arr - 14.0))),
                            int(np.argmin(np.abs(s_arr - 156.0)))]

        blob = codec.pack(pulse_id, {
            "s": res.s, "w": res.w, "cx": res.cx, "cy": res.cy,
            "sig_x": res.sig_x, "sig_y": res.sig_y, "sig_z": res.sig_z,
            "transmission": res.transmission, "loss_wpm": res.loss_wpm,
            "current_ma": res.current_ma,
            "bpm_x": res.bpm_x, "bpm_y": res.bpm_y,
            "bpm_phase": res.bpm_phase, "bpm_sum": res.bpm_sum,
            "blm_wpm": res.blm_wpm, "toroid_i": res.toroid_i,
            "bpm_w": res.bpm_w,
            "beam_on": np.array([1.0 if beam_on else 0.0]),
            "wcm_sig_ps": self._wcm_sig_ps(res),
            "scraper_frac": np.array(
                [self.engine.scrape_out.get(e.name, 0.0)
                 for e in self.lat.elements if e.type == "scraper2"],
                dtype=np.float32),
        })
        # ---- Booster injection figure of merit (at the foil)
        try:
            from pip2va.physics import injection as _inj
            if not hasattr(self, "_foil_j"):
                self._foil_j = next(
                    (i for i, e in enumerate(self.lat.elements)
                     if e.type == "foil"), len(res.s) - 1)
                self.r.hsetnx(keys.settings("injection", "main"),
                              "bump0_mm", 8.0)
                self.r.hsetnx(keys.settings("injection", "main"),
                              "decay_turns", 12.0)
                from pip2va.common import schema
                schema.register_settings(self.r, "injection",
                    {"bump0_mm": {"lo": 0.5, "hi": 25.0, "unit": "mm"},
                     "decay_turns": {"lo": 5.0, "hi": 285.0}},
                    pv="PIP2:INJ")
            j = self._foil_j
            inj_st = self.read_hash(keys.settings("injection", "main"))
            bpg_ok = True
            try:
                mm = self.r.hget("state:bpg", "mismatch_buckets")
                bpg_ok = (mm is None) or int(mm) == 0
            except (TypeError, ValueError):
                pass
            chop = ds.get("MEBT:CHOP1", {})
            from pip2va.common.bpg import avg_duty
            duty = avg_duty(chop) if chop else 0.4
            # real momentum spread + normalised emittance at the exit/foil
            dpp = float(getattr(res, "dpp", 0.0) or 7e-4)
            q = _inj.score(
                i_out_ma=float(res.current_ma[j] if hasattr(
                    res.current_ma, "__len__") else res.current_ma),
                eps_x_um=float(getattr(res, "emit_x_um", 0.0)),
                eps_y_um=float(getattr(res, "emit_y_um", 0.0)),
                sig_x_mm=float(res.sig_x[j]) * 1e3,
                sig_y_mm=float(res.sig_y[j]) * 1e3,
                cx_mm=float(res.cx[j]) * 1e3,
                cy_mm=float(res.cy[j]) * 1e3,
                dpp_rms=dpp,
                bump0_mm=float(inj_st.get("bump0_mm", 8.0)),
                decay_turns=float(inj_st.get("decay_turns", 12.0)),
                notch_ok=bpg_ok, duty=duty)
            if beam_on:
                self.r.hset("state:injection", mapping={
                    k: round(float(v), 4) for k, v in q.items()})
        except Exception:
            pass
        lag_ms = (time.perf_counter() - t0) * 1e3
        pipe = self.r.pipeline(transaction=False)
        pipe.hset(keys.truth("beam"), "d", blob)
        bstate = {
            "pulse_id": pulse_id,
            "w_out": float(res.w[-1]),
            "transmission": float(res.transmission[-1]),
            "i_out_ma": float(res.current_ma[-1]),
            "lag_ms": lag_ms,
            "stale": int(stale),
            "permit": int(beam_on),
        }
        pipe.hset("state:beam", mapping=bstate)
        # also stream it so the aggregate values rewind with the DVR
        pipe.xadd(keys.stream("beam.state"),
                  {"d": json.dumps({k: float(v) for k, v in bstate.items()})},
                  maxlen=self.settings.stream_maxlen, approximate=True)
        pipe.execute()
        if lag_ms > 45.0:
            log.warning("envelope pass lag %.1f ms", lag_ms)

    # ------------------------------------------------------------ deep pass

    def _glitch_fault(self) -> float:
        if not hasattr(self, "_gf_t") or time.time() - self._gf_t > 2.0:
            self._gf_t = time.time()
            f = self.r.hgetall(keys.fault("source", "main"))
            self._gf = (float(f.get(b"magnitude", 1.0))
                        if f.get(b"type") == b"glitchy" else 1.0)
        return max(self._gf, 1.0)

    def _wcm_sig_ps(self, res):
        out = []
        for j in self._wcm_js:
            gam = 1.0 + res.w[j] / 939.294
            bet = float(np.sqrt(max(1 - 1 / gam ** 2, 1e-9)))
            out.append(res.sig_z[j] / (bet * 3e8) * 1e12)
        return np.array(out, dtype=np.float32)

    def _macro_loop(self):
        tracker = MacroTracker(self.lat, n=self.settings.macro_particles,
                               errors=self._errors)
        log.info("macro tracker running (n=%d, backend=%s)",
                 tracker.n, tracker.xp.__name__)
        while True:
            snap = self._latest
            station = self.read_hash(keys.settings("wf3d", "main")).get(
                "station") or None
            try:
                res = tracker.run(snap["ds"], beam_on=snap["beam_on"],
                                  cloud_at=station)
            except Exception:
                log.exception("macro pass failed")
                time.sleep(2.0)
                continue
            data = {
                "alive_frac": res.alive_fraction, "w_out": res.w_out,
                "emit_s": res.emit_s, "emit_x_um": res.emit_x_um,
                "emit_y_um": res.emit_y_um, "sig_x_mm": res.sig_x_mm,
                "sig_y_mm": res.sig_y_mm,
                "loss_count": res.loss_count.astype(float),
            }
            for name, (hx, hy, edges) in res.profiles.items():
                data[f"prof:{name}:x"] = hx
                data[f"prof:{name}:y"] = hy
                data[f"prof:{name}:edges"] = edges
            for sec, planes in res.phase_space.items():
                for pl, (img, ext) in planes.items():
                    data[f"ps:{sec}:{pl}"] = img
                    data[f"ps:{sec}:{pl}:ext"] = ext
            if res.cloud is not None:
                data["cloud"] = res.cloud
                data["cloud_at"] = res.cloud_at
            # deep diagnostic pass: ~0.5 Hz is plenty for phase-space /
            # emittance / cloud, and each message is ~1 MB — publishing at
            # pulse rate floods the GUI (renders can't keep up) and Redis.
            # keep only a few entries: it is a latest-snapshot diagnostic.
            self.publish_stream("beam.deep", snap["pulse_id"], data, maxlen=8)
            time.sleep(2.0)


if __name__ == "__main__":
    main_for(BeamPhysicsService)
