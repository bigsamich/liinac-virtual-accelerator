#!/usr/bin/env python3
"""Smoke-test a running docker compose stack from the host."""
import sys
import time

import numpy as np
import redis

sys.path.insert(0, ".")
from pip2va.common import codec, keys  # noqa: E402

SERVICES = ("timing", "beam-physics", "rf-sim", "magnet-sim", "diag-sim",
            "mps", "autotune")


def main():
    r = redis.Redis.from_url("redis://localhost:6379/0")
    r.ping()
    print("redis: OK")

    deadline = time.time() + 60
    missing = set(SERVICES)
    while missing and time.time() < deadline:
        missing = {s for s in SERVICES if not r.exists(keys.heartbeat(s))}
        if missing:
            time.sleep(1.0)
    assert not missing, f"no heartbeat from: {missing}"
    print(f"heartbeats: all {len(SERVICES)} services alive")

    last = r.xrevrange(keys.stream("bpm.orbit"), count=1)
    last_id = last[0][0].decode() if last else "0-0"
    time.sleep(3.0)
    new = r.xrange(keys.stream("bpm.orbit"), min=f"({last_id}")
    rate = len(new) / 3.0
    assert rate > 15, f"orbit stream at {rate:.1f}/s, expected ~20"
    print(f"orbit stream: {rate:.1f} entries/s")

    st = {k.decode(): v.decode() for k, v in r.hgetall("state:beam").items()}
    print(f"beam: W={float(st['w_out']):.1f} MeV  "
          f"T={float(st['transmission']):.4f}  lag={float(st['lag_ms']):.1f} ms")
    assert abs(float(st["w_out"]) - 800.0) < 25.0

    # a corrector step must move the measured orbit
    def mean_orbit(n=20):
        xs = []
        for _, fields in r.xrevrange(keys.stream("bpm.orbit"), count=n):
            _, d = codec.unpack(fields[b"d"])
            xs.append(d["x"])
        return np.mean(xs, axis=0)

    corr = "SSR2:C10"
    x0 = mean_orbit()
    r.hset(keys.settings("magnet", corr), "current_x", 3.0)
    r.publish(keys.CH_SETTINGS,
              '{"key": "%s"}' % keys.settings("magnet", corr))
    time.sleep(3.0)
    x1 = mean_orbit()
    delta = np.abs(x1 - x0).max()
    r.hset(keys.settings("magnet", corr), "current_x", 0.0)
    r.publish(keys.CH_SETTINGS,
              '{"key": "%s"}' % keys.settings("magnet", corr))
    assert delta > 20e-6, f"corrector moved orbit only {delta*1e6:.1f} um"
    print(f"corrector response: {delta*1e6:.0f} um orbit shift  OK")

    deep = r.xlen(keys.stream("beam.deep"))
    print(f"deep stream: {deep} macro passes published")
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
