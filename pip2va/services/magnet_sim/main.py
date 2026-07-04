"""Magnet power-supply simulator.

Owns every solenoid, quad, and corrector: seeds setpoint hashes from the
lattice design, slews readbacks toward setpoints with per-family time
constants, adds ripple + thermal drift, honors fault injection (trip), and
publishes readback hashes + one stream:magnet.readback entry per pulse.
"""
from __future__ import annotations

import json

import numpy as np

from pip2va.common import keys
from pip2va.common.devmodel import FirstOrderDevice
from pip2va.services.base import Service, main_for

TAU = {"solenoid": 3.0, "quad": 0.8, "corrector": 0.3}
RIPPLE = {"solenoid": 3e-5, "quad": 5e-5, "corrector": 5e-5}
DRIFT_PER_HR = {"solenoid": 5e-5, "quad": 2e-4, "corrector": 0.0}


class MagnetSimService(Service):
    name = "magnet-sim"
    extra_channels = (keys.CH_SETTINGS,)

    def on_start(self):
        rng = np.random.default_rng(2026)
        self.devices: list[tuple] = []   # (el, field, device, skey, rkey)
        self.dt = 1.0 / self.settings.tick_hz
        for el in self.lat.elements:
            if el.type in ("solenoid", "quad"):
                fields = [("current", el.params["design_current"])]
            elif el.type == "corrector":
                fields = [("current_x", 0.0), ("current_y", 0.0)]
            else:
                continue
            skey = keys.settings("magnet", el.name)
            rkey = keys.readback("magnet", el.name)
            for f, sp in fields:
                self.r.hsetnx(skey, f, sp)
                dev = FirstOrderDevice(
                    float(self.r.hget(skey, f)), TAU[el.type],
                    RIPPLE[el.type], DRIFT_PER_HR[el.type], rng)
                self.devices.append((el, f, dev, skey, rkey))
        self.r.set("lattice:magnet.index",
                   json.dumps([f"{el.name}:{f}" for el, f, *_ in self.devices]))
        self._dirty = {skey for _, _, _, skey, _ in self.devices}

    def on_event(self, channel, data):
        if isinstance(data, dict) and "key" in data:
            self._dirty.add(data["key"])

    def on_tick(self, pulse_id: int):
        vals = np.zeros(len(self.devices), dtype=np.float32)
        stats = np.zeros(len(self.devices), dtype=np.float32)
        pipe = self.r.pipeline(transaction=False)
        seen_settings: dict[str, dict] = {}
        for i, (el, f, dev, skey, rkey) in enumerate(self.devices):
            if skey in self._dirty and skey not in seen_settings:
                seen_settings[skey] = self.read_hash(skey)
            st = seen_settings.get(skey)
            if st is not None:
                dev.setpoint = float(st.get(f, dev.setpoint))
            # fault injection
            fkey = keys.fault("magnet", el.name)
            if self.r.exists(fkey):
                fl = self.read_hash(fkey)
                if fl.get("type") == "trip" and not dev.tripped:
                    dev.trip()
                    self.publish_event(keys.CH_FAULT, {"key": rkey})
                elif fl.get("type") == "drift":
                    dev.drift += float(fl.get("magnitude", 0.0)) * self.dt
            elif dev.tripped and st is not None and st.get("reset"):
                dev.try_reset()
                pipe.hdel(skey, "reset")
            rb = dev.step(self.dt)
            vals[i] = rb
            stats[i] = 1.0 if dev.tripped else 0.0
            cal = (el.params.get("field_per_amp")
                   or el.params.get("grad_per_amp")
                   or el.params.get("bl_per_amp") or 0.0)
            pipe.hset(rkey, mapping={
                f: rb, "status": "tripped" if dev.tripped else "ok",
                f.replace("current", "field"): rb * cal})
        for skey in seen_settings:
            self._dirty.discard(skey)
        pipe.execute()
        self.publish_stream("magnet.readback", pulse_id,
                            {"values": vals, "status": stats})


if __name__ == "__main__":
    main_for(MagnetSimService)
