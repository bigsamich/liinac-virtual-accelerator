"""Shared service framework: Redis wiring, tick subscription, heartbeats.

A Service subscribes to the timing service's pulse.tick channel plus any
extra_channels, and dispatches to on_tick(pulse_id) / on_event(channel, data).
Subclasses that generate their own schedule (the timing service itself)
override run() completely.
"""
from __future__ import annotations

import json
import logging
import signal
import time

import redis

from pip2va.common import codec, keys
from pip2va.common.config import Settings
from pip2va.common.lattice import Lattice, load_lattice

log = logging.getLogger(__name__)


class Service:
    name = "base"
    extra_channels: tuple[str, ...] = ()

    def __init__(self, redis_client=None, settings: Settings | None = None,
                 lattice: Lattice | None = None):
        self.settings = settings or Settings()
        self.r = redis_client if redis_client is not None else \
            redis.Redis.from_url(self.settings.redis_url)
        self.lat = lattice or load_lattice()
        self._running = False
        self._last_hb = 0.0

    # ------------------------------------------------------------ lifecycle

    def run(self):
        """Blocking main loop: dispatch ticks and events."""
        self._running = True
        ps = self.r.pubsub(ignore_subscribe_messages=True)
        ps.subscribe(keys.CH_TICK, *self.extra_channels)
        self.on_start()
        log.info("%s: running", self.name)
        while self._running:
            self.heartbeat()
            msg = ps.get_message(timeout=0.2)
            if not msg or msg["type"] != "message":
                continue
            ch = msg["channel"]
            ch = ch.decode() if isinstance(ch, bytes) else ch
            try:
                data = json.loads(msg["data"])
            except (ValueError, TypeError):
                data = msg["data"]
            try:
                if ch == keys.CH_TICK:
                    self.on_tick(int(data["pulse_id"]))
                else:
                    self.on_event(ch, data)
            except Exception:
                log.exception("%s: handler error on %s", self.name, ch)
        ps.close()

    def stop(self):
        self._running = False

    def install_signal_handlers(self):
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

    # ------------------------------------------------------------ hooks

    def on_start(self):
        pass

    def on_tick(self, pulse_id: int):
        pass

    def on_event(self, channel: str, data):
        pass

    # ------------------------------------------------------------ helpers

    def heartbeat(self, period: float = 1.0):
        now = time.monotonic()
        if now - self._last_hb >= period:
            self.r.set(keys.heartbeat(self.name), int(time.time()), ex=5)
            self._last_hb = now

    def publish_stream(self, product: str, pulse_id: int, data: dict):
        self.r.xadd(keys.stream(product), {"d": codec.pack(pulse_id, data)},
                    maxlen=self.settings.stream_maxlen, approximate=True)

    def publish_event(self, channel: str, payload: dict):
        self.r.publish(channel, json.dumps(payload))

    def read_hash(self, key: str) -> dict:
        raw = self.r.hgetall(key)
        out = {}
        for k, v in raw.items():
            k = k.decode() if isinstance(k, bytes) else k
            v = v.decode() if isinstance(v, bytes) else v
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v
        return out


def main_for(service_cls, **kwargs):
    """Entry-point boilerplate for a service container."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    svc = service_cls(**kwargs)
    svc.install_signal_handlers()
    svc.run()
