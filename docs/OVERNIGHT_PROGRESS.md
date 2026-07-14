# Overnight Build Progress

- start: baseline 89 tests green, branch overnight-build
- Phase 1 (deterministic core): common/rng.py counter-based RNG, devmodel+magnet retrofit, sim/driver.py single-process driver, tests/test_determinism.py (bit-exact + causality + CRN). 93 tests green.
- Phase 2 (time-travel): sim/snapshot.py (capture/restore), sim/eventlog.py (append-only, deterministic order), tests/test_timetravel.py — snapshot->restore->replay bit-exact. 96 tests.
- Phase 3 (commit-horizon input): sim/input.py InputInjector. Phase 4 (branch engine): sim/branch.py fork/evaluate with CRN + parallel workers. tests: commit-horizon determinism+replay, CRN, isolation, parallel==serial, delta-moves-outcome.
- Phase 6 (automation): analysis/optimizer.py pattern-search maximize + CRN sensitivity + autotune_injection. Driver now computes injection score + knobs. Demo: injection 18.5->67.1 deterministically. 103 tests.
- Phase 7 (physics): losses.lorentz_strip_frac_per_m (Keating), wired into envelope dipole loss + lorentz_scale knob. Negligible at 0.24T, exponential above knee. 108 tests.
- Phase 8 core: sim/replay.py record-replay + first_divergence. Bonus: EPICS iface-pinned multicast, make determinism, guide 08 + OVERNIGHT_REPORT. 110 tests.
