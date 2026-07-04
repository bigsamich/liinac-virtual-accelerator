#!/usr/bin/env python3
"""Benchmark the per-pulse envelope pass and the macroparticle pass."""
import time

from pip2va.common.lattice import load_lattice
from pip2va.physics.envelope import EnvelopeEngine
from pip2va.physics.macro import MacroTracker

lat = load_lattice()
eng = EnvelopeEngine(lat)
eng.run({}, current_ma=2.0)  # warm-up

t0 = time.perf_counter()
n = 50
for _ in range(n):
    eng.run({}, current_ma=2.0)
dt = (time.perf_counter() - t0) / n * 1e3
print(f"envelope pass: {dt:.2f} ms/pulse  (budget 15 ms, tick 50 ms)")

for backend, np_ in (("numpy", 20_000), ("auto", 100_000)):
    try:
        trk = MacroTracker(lat, n=np_, backend=backend)
        t0 = time.perf_counter()
        res = trk.run({}, current_ma=2.0)
        dt = time.perf_counter() - t0
        print(f"macro pass [{backend}, n={np_:,}]: {dt*1e3:.0f} ms/pass "
              f"(alive {res.alive_fraction:.3f}, W={res.w_out:.1f})")
    except Exception as e:
        print(f"macro pass [{backend}]: unavailable ({e})")
