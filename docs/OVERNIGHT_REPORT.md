# Overnight Build — Report

**Branch:** `overnight-build` (not merged — review before merging to `main`).
**Tests:** 89 → **110 green** (21 new). `make determinism` is the bit-exact gate.

## Landed (tested, committed)

| Phase | What | Commit |
|---|---|---|
| **1 — Deterministic core** | `common/rng.py` counter-based RNG (pure fn of `seed,pulse_id,entity,channel`); `devmodel`+`magnet_sim` retrofit; `sim/driver.py` single-process driver; bit-exact + causality + CRN tests | `7df141d` |
| **2 — Time-travel** | `sim/snapshot.py` capture/restore; `sim/eventlog.py` append-only deterministic log; snapshot→restore→replay bit-exact | `55273c4` |
| **3 — Commit-horizon input** | `sim/input.py` injector (rollback-netcode); deterministic + replayable | `1f28608` |
| **4 — Branch engine** | `sim/branch.py` fork/evaluate with CRN, parallel==serial | `1f28608` |
| **6 — Automation** | `analysis/optimizer.py` pattern-search + CRN sensitivity + `autotune_injection`; driver computes injection score. **Demo: 18.5 → 67.1 deterministically** | `a91a792` |
| **7 — Physics** | Lorentz/magnetic stripping in BTL dipoles (Keating), `lorentz_scale` knob; negligible at 0.24 T, exponential above the knee | `5783076` |
| **8 — Observability (core)** | `sim/replay.py` record-replay + `first_divergence` localizer; `make determinism` target | (this commit) |
| **Bonus** | EPICS server multicast **iface-pinned** (`,ttl@$EPICS_HOST_INTERFACE`) so discovery survives container recreation — fixes the SPARK-not-discoverable bug; `docs/guides/08-determinism-and-branching.md` | (this commit) |

## Deliberately skipped

- **Phase 5 (DES kernel)** — per instruction ("we do not need the kernel yet").
- **Phase 9 (GUI pages)** — timeline/branch, what-if heatmap, auto-tune page,
  causal inspector. Left for review; the engines are all in place and have
  clean APIs (`branch.fork/evaluate`, `optimizer.*`, `replay.first_divergence`).
- **Deeper Phase 8** — full causal *slicing* (read/write-set provenance per
  stage) beyond first-divergence localization.
- **Phase 7 longitudinal dynamics** — Lorentz stripping landed; the (φ,W)
  synchrotron/debuncher model feeding real dp/p into the injection score is the
  larger remaining physics item.
- **Bonus grab-bag not done:** `make_insights.py`, reproducible dataset build
  seeding, per-run manifest, fast-forward mode.

## Next session (prioritized)

1. **GUI what-if page** — fork from the live snapshot, run K branches, compare;
   then the auto-tune page (wraps `optimizer.autotune_injection`). Biggest
   visible payoff; all backend APIs exist.
2. **Wire the branch engine to the live machine** — build a snapshot from live
   Redis state so branches fork from *now*, not a cold driver.
3. **Retrofit remaining noise sources** to `pulse_rng` (diag waveforms, RF
   microphonics, macro init) so the *live distributed* system is deterministic
   too, not just the driver.
4. **Longitudinal dynamics** (φ,W) → real dp/p into the injection score.
5. **make_insights.py** — the missing (human-gated) insight generator.

## How to verify

```bash
make determinism            # bit-exact gate (fast)
OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests/ -q   # full suite (110)
```
