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

    def run(self):
        self._running = True
        period = 1.0 / self.tick_hz
        next_t = time.monotonic() + period
        while self._running:
            now = time.monotonic()
            if now < next_t:
                time.sleep(min(next_t - now, 0.05))
                continue
            # absolute schedule: late ticks don't shift the timebase
            next_t += period
            if now - next_t > 1.0:      # fell way behind (suspend): resync
                next_t = now + period
            self.pulse_id += 1
            payload = {"pulse_id": self.pulse_id, "t": time.time()}
            self.r.publish(keys.CH_TICK, json.dumps(payload))
            self.r.xadd(keys.stream("timing.tick"),
                        {"d": json.dumps(payload)},
                        maxlen=self.settings.stream_maxlen, approximate=True)
            self.heartbeat()


if __name__ == "__main__":
    main_for(TimingService)
