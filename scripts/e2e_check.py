#!/usr/bin/env python3
"""End-to-end validation against a live compose stack.

Checks: sustained 20 Hz, envelope lag budget, corrector orbit response,
cavity-trip -> MPS trip -> recovery cycle. Run after `docker compose up -d`
and after the MPS baseline capture has armed (~15 s).
"""
import json
import sys
import time

import numpy as np
import redis

sys.path.insert(0, ".")
from pip2va.common import codec, keys  # noqa: E402

R = redis.Redis.from_url("redis://localhost:6379/0")


def state(field):
    v = R.hget("state:beam", field)
    return float(v) if v is not None else None


def wait_for(cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.5)
    raise AssertionError(f"timeout waiting for {what}")


def notify_settings(key):
    R.publish(keys.CH_SETTINGS, json.dumps({"key": key}))


def mean_orbit(n=20):
    xs = [codec.unpack(f[b"d"])[1]["x"]
          for _, f in R.xrevrange(keys.stream("bpm.orbit"), count=n)]
    return np.mean(xs, axis=0)


def main():
    print("== e2e: PIP-II virtual accelerator ==")

    # 0. armed + beam on (clear any latched trip from earlier experiments)
    def ensure_permit():
        if R.get("state:mps.permit") != b"1":
            R.hset(keys.settings("mps", "main"), "reset", 1)
        return R.get("state:mps.permit") == b"1"
    wait_for(ensure_permit, 60, "beam permit")
    print("permit: ON")

    # 1. sustained rate over 30 s + lag budget
    last = R.xrevrange(keys.stream("bpm.orbit"), count=1)[0][0].decode()
    lags = []
    t0 = time.time()
    while time.time() - t0 < 30.0:
        lags.append(state("lag_ms"))
        time.sleep(0.5)
    pulses = len(R.xrange(keys.stream("bpm.orbit"), min=f"({last}"))
    rate = pulses / 30.0
    p95 = float(np.percentile(lags, 95))
    print(f"rate: {rate:.2f} Hz over 30 s ({pulses} pulses), "
          f"lag p95 {p95:.1f} ms")
    assert pulses >= 580, f"only {pulses} pulses in 30 s"
    assert p95 < 50.0

    # 2. corrector orbit response (gentle: big kicks rightly trip the MPS)
    corr = keys.settings("magnet", "LB650:C5")
    x0 = mean_orbit()
    R.hset(corr, "current_x", 1.0)
    notify_settings(corr)
    time.sleep(3.0)
    d = np.abs(mean_orbit() - x0).max()
    R.hset(corr, "current_x", 0.0)
    notify_settings(corr)
    print(f"corrector step: {d*1e6:.0f} um max orbit shift")
    assert d > 20e-6
    time.sleep(3.0)
    wait_for(ensure_permit, 30, "permit after corrector test")

    # 3. cavity trip -> energy drop -> losses -> MPS trip
    w0 = state("w_out")
    assert w0 and w0 > 700.0, f"beam not at energy before trip test (W={w0})"
    cav = "LB650:CAV17"
    R.hset(keys.fault("rf", cav), mapping={"type": "trip", "magnitude": 1})

    def energy_dropped():
        w = state("w_out")
        return w is not None and w < w0 - 5.0
    wait_for(energy_dropped, 15, "energy drop after cavity trip")
    print(f"cavity {cav} tripped: W {w0:.1f} -> {state('w_out'):.1f} MeV")
    wait_for(lambda: R.get("state:mps.permit") == b"0", 30,
             "MPS trip on losses")
    print("MPS: beam permit dropped  OK")
    assert state("transmission") == 0.0

    # 4. recovery: clear fault, reset cavity, reset MPS
    R.delete(keys.fault("rf", cav))
    R.hset(keys.settings("rf", cav), "reset", 1)
    notify_settings(keys.settings("rf", cav))
    time.sleep(2.0)
    R.hset(keys.settings("mps", "main"), "reset", 1)
    wait_for(lambda: R.get("state:mps.permit") == b"1", 30, "permit restore")
    def energy_recovered():
        w = state("w_out")
        return w is not None and w > w0 - 15.0
    wait_for(energy_recovered, 30, "energy recovery")
    print(f"recovery: W {state('w_out'):.1f} MeV, "
          f"T {state('transmission'):.4f}, permit ON")

    print("\nE2E CHECK PASSED")


if __name__ == "__main__":
    main()
