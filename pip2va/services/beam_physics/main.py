"""beam-physics service — the simulation core.

Every pulse.tick: bulk-reads all device readbacks into a DeviceState snapshot,
runs the envelope engine, and writes ground truth (truth:beam) plus a summary
(state:beam). A daemon thread free-runs the GPU macroparticle tracker on the
latest snapshot and publishes stream:beam.deep after each full pass.

The GUI never reads truth:beam — diag-sim turns it into noisy measurements.
"""
from __future__ import annotations

import logging
import threading
import time

from pip2va.common import codec, keys
from pip2va.physics.envelope import EnvelopeEngine
from pip2va.physics.macro import MacroTracker
from pip2va.services.base import Service, main_for

log = logging.getLogger(__name__)


class BeamPhysicsService(Service):
    name = "beam-physics"

    def __init__(self, redis_client=None, settings=None, macro: bool = True):
        super().__init__(redis_client=redis_client, settings=settings)
        self._macro_enabled = macro

    def on_start(self):
        self.engine = EnvelopeEngine(self.lat)
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
        raw = pipe.execute()
        ds: dict = {}
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
        ds, stale = self._collect_device_state()
        permit = self.r.get("state:mps.permit")
        beam_on = permit is None or permit in (b"1", "1")
        res = self.engine.run(ds, beam_on=beam_on)
        self._latest = {"ds": ds, "beam_on": beam_on, "pulse_id": pulse_id}

        blob = codec.pack(pulse_id, {
            "s": res.s, "w": res.w, "cx": res.cx, "cy": res.cy,
            "sig_x": res.sig_x, "sig_y": res.sig_y, "sig_z": res.sig_z,
            "transmission": res.transmission, "loss_wpm": res.loss_wpm,
            "current_ma": res.current_ma,
            "bpm_x": res.bpm_x, "bpm_y": res.bpm_y,
            "bpm_phase": res.bpm_phase, "bpm_sum": res.bpm_sum,
            "blm_wpm": res.blm_wpm, "toroid_i": res.toroid_i,
        })
        lag_ms = (time.perf_counter() - t0) * 1e3
        pipe = self.r.pipeline(transaction=False)
        pipe.hset(keys.truth("beam"), "d", blob)
        pipe.hset("state:beam", mapping={
            "pulse_id": pulse_id,
            "w_out": float(res.w[-1]),
            "transmission": float(res.transmission[-1]),
            "i_out_ma": float(res.current_ma[-1]),
            "lag_ms": lag_ms,
            "stale": int(stale),
            "permit": int(beam_on),
        })
        pipe.execute()
        if lag_ms > 45.0:
            log.warning("envelope pass lag %.1f ms", lag_ms)

    # ------------------------------------------------------------ deep pass

    def _macro_loop(self):
        tracker = MacroTracker(self.lat, n=self.settings.macro_particles)
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
            self.publish_stream("beam.deep", snap["pulse_id"], data)
            time.sleep(0.05)


if __name__ == "__main__":
    main_for(BeamPhysicsService)
