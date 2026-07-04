"""Timing service: 20 Hz master clock."""
import json
import threading
import time

import fakeredis

from pip2va.common import keys
from pip2va.services.timing.main import TimingService


def test_ticks_monotonic_and_at_rate():
    r = fakeredis.FakeStrictRedis()
    svc = TimingService(redis_client=r, tick_hz=20.0)
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(keys.CH_TICK)

    th = threading.Thread(target=svc.run, daemon=True)
    th.start()
    t0 = time.monotonic()
    msgs = []
    while time.monotonic() - t0 < 1.05:
        m = ps.get_message(timeout=0.1)
        if m and m["type"] == "message":
            msgs.append(json.loads(m["data"]))
    svc.stop()
    th.join(timeout=2)

    assert len(msgs) >= 18, f"only {len(msgs)} ticks in ~1 s"
    ids = [m["pulse_id"] for m in msgs]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    # stream mirror advances too
    assert r.xlen(keys.stream("timing.tick")) >= 18
    # heartbeat present
    assert r.get(keys.heartbeat("timing")) is not None
