"""Timing service: the 20 Hz master clock.

Publishes pulse.tick with a monotonically increasing pulse ID using
absolute-deadline scheduling (no drift accumulation), and mirrors ticks to
stream:timing.tick for late joiners.
"""
from __future__ import annotations

import json
import time

from pip2va.common import keys
from pip2va.services.base import Service, main_for


class TimingService(Service):
    name = "timing"

    def __init__(self, redis_client=None, settings=None, tick_hz: float | None = None):
        super().__init__(redis_client=redis_client, settings=settings)
        self.tick_hz = tick_hz or self.settings.tick_hz
        self.pulse_id = 0
        from .utilities import UtilityModel
        self.util = UtilityModel()
        self._util_next = 0.0

    def run(self):
        self._running = True
        period = 1.0 / self.tick_hz
        next_t = time.monotonic() + period
        self._last_step = int(self.r.get("state:sim.step") or 0)
        while self._running:
            # ---- pause / single-step control (DVR) ----
            if self.r.get("state:sim.run") == b"0":
                step = int(self.r.get("state:sim.step") or 0)
                if step == self._last_step:
                    time.sleep(0.03)          # frozen: hold the clock
                    self.heartbeat()
                    continue
                self._last_step = step        # one step requested -> tick once
                next_t = time.monotonic() + period
            else:
                now = time.monotonic()
                if now < next_t:
                    time.sleep(min(next_t - now, 0.05))
                    continue
                # absolute schedule: late ticks don't shift the timebase
                next_t += period
                if now - next_t > 1.0:        # fell way behind: resync
                    next_t = now + period
            now = time.monotonic()
            self.pulse_id += 1
            payload = {"pulse_id": self.pulse_id, "t": time.time()}
            self.r.publish(keys.CH_TICK, json.dumps(payload))
            self.r.xadd(keys.stream("timing.tick"),
                        {"d": json.dumps(payload)},
                        maxlen=self.settings.stream_maxlen, approximate=True)
            if now >= self._util_next:
                self._util_next = now + 1.0
                st = self.read_hash(keys.settings("util", "main"))
                p, lcw = self.util.step(
                    1.0,
                    lcw_offset=float(st.get("lcw_offset_c", 0.0)),
                    cryo_offset=float(st.get("cryo_offset_mbar", 0.0)),
                    cryo_cm=str(st.get("cryo_cm", "")))
                self.r.set("state:util", self.util.pack(p, lcw))
            self.heartbeat()


if __name__ == "__main__":
    main_for(TimingService)
