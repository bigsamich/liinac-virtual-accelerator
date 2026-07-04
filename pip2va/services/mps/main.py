"""Machine Protection System: beam-permit watchdog.

Watches the measured BLM stream; if the 10-pulse rolling mean at any monitor
exceeds its threshold, drops the beam permit (state:mps.permit=0), latches,
and logs to stream:mps.events. Reset (settings:mps:main reset=1) is accepted
only once the rolling loss is back under threshold.

Thresholds come from a commissioning-style baseline capture: for the first
`learn_pulses` after start (or after settings:mps:main relearn=1) the MPS
records per-BLM mean/std of the running machine and sets
threshold = max(hands-on limit, 3 x design level, mean + 6 sigma, 2 x mean).
Device fault events are logged to the same event stream.
"""
from __future__ import annotations

import collections
import time

import numpy as np

from pip2va.common import codec, keys
from pip2va.services.base import Service, main_for

WINDOW = 10


class MpsService(Service):
    name = "mps"
    extra_channels = (keys.CH_FAULT,)

    def __init__(self, redis_client=None, settings=None, learn_pulses: int = 200):
        super().__init__(redis_client=redis_client, settings=settings)
        self.learn_pulses = learn_pulses

    def on_start(self):
        self.r.setnx("state:mps.permit", 1)
        self.limit = self.lat.meta.get("loss_limit_wpm", 1.0)
        blms = self.lat.instruments("blm")
        self.blm_names = [e.name for e in blms]
        # static floor: generic limit, or 3x the design level where by-design
        # losses (chopper/scraper regions) exceed it
        self.base_thresholds = np.array([
            max(self.limit, 3.0 * e.params.get("design_wpm", 0.0))
            for e in blms])
        self.thresholds = self.base_thresholds.copy()
        self.window: collections.deque = collections.deque(maxlen=WINDOW)
        self._learn_left = self.learn_pulses
        self._learn_n = 0
        self._learn_sum = np.zeros(len(blms))
        self._learn_sq = np.zeros(len(blms))
        if self.learn_pulses:
            self._event("learning", f"baseline capture, {self.learn_pulses} pulses")

    def _finish_learning(self):
        n = max(self._learn_n, 1)
        mean = self._learn_sum / n
        std = np.sqrt(np.maximum(self._learn_sq / n - mean ** 2, 0.0))
        m = min(len(mean), len(self.base_thresholds))
        self.thresholds = np.maximum(
            self.base_thresholds[:m],
            np.maximum(mean[:m] + 6.0 * std[:m], 2.0 * mean[:m]))
        self.r.set("state:mps.thresholds",
                   codec.pack(0, {"wpm": self.thresholds}))
        self._event("armed", f"thresholds set from {n}-pulse baseline")

    def _event(self, kind: str, detail: str):
        self.r.xadd(keys.stream("mps.events"),
                    {"t": time.time(), "kind": kind, "detail": detail},
                    maxlen=500, approximate=True)

    def on_event(self, channel, data):
        if channel == keys.CH_FAULT and isinstance(data, dict):
            self._event("device_fault", str(data.get("key", "?")))

    def on_tick(self, pulse_id: int):
        entries = self.r.xrevrange(keys.stream("blm.losses"), count=1)
        if entries:
            _, wpm = codec.unpack(entries[0][1][b"d"])
            self.window.append(wpm["wpm"])
            if self._learn_left > 0:
                # only learn from a machine that is actually delivering beam —
                # capturing dark current would collapse thresholds to the floor
                beam = self.read_hash("state:beam")
                delivering = (self.r.get("state:mps.permit") in (b"1", "1")
                              and beam.get("transmission", 0.0) > 0.5)
                if delivering:
                    v = wpm["wpm"]
                    if len(v) == len(self._learn_sum):
                        self._learn_sum += v
                        self._learn_sq += v ** 2
                        self._learn_n += 1
                    self._learn_left -= 1
                    if self._learn_left == 0:
                        self._finish_learning()
        if not self.window:
            return
        mean = np.mean(np.stack(self.window), axis=0)
        thr = self.thresholds[:len(mean)] if len(mean) <= len(self.thresholds) \
            else np.full(len(mean), self.limit)
        learning = self._learn_left > 0
        if learning:
            thr = thr * 5.0   # commissioning mode: lenient but never unprotected
        excess = mean / thr
        worst = int(np.argmax(excess))
        permit = self.r.get("state:mps.permit") in (b"1", "1", None)

        if permit and len(self.window) >= WINDOW and excess[worst] > 1.0:
            self.r.set("state:mps.permit", 0)
            name = (self.blm_names[worst]
                    if worst < len(self.blm_names) else f"BLM{worst}")
            self._event("trip", f"{name} {mean[worst]:.2f} W/m "
                                f"(limit {thr[worst]:.2f})")
            self.publish_event(keys.CH_MPS, {"permit": 0, "blm": name,
                                             "wpm": float(mean[worst])})

        # reset / relearn requests
        skey = keys.settings("mps", "main")
        st = self.read_hash(skey)
        if st.get("relearn"):
            self.r.hdel(skey, "relearn")
            self._learn_left = self.learn_pulses or 200
            self._learn_n = 0
            self._learn_sum[:] = 0.0
            self._learn_sq[:] = 0.0
            self._event("learning", "baseline re-capture requested")
            return
        if st.get("reset"):
            self.r.hdel(skey, "reset")
            if excess[worst] <= 1.0:
                self.r.set("state:mps.permit", 1)
                self._event("reset", "permit restored")
                self.publish_event(keys.CH_MPS, {"permit": 1})
            else:
                self._event("reset_refused",
                            f"loss still {mean[worst]:.2f} W/m")


if __name__ == "__main__":
    main_for(MpsService)
