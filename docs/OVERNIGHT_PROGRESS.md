# Overnight Build Progress

- start: baseline 89 tests green, branch overnight-build
- Phase 1 (deterministic core): common/rng.py counter-based RNG, devmodel+magnet retrofit, sim/driver.py single-process driver, tests/test_determinism.py (bit-exact + causality + CRN). 93 tests green.
- Phase 2 (time-travel): sim/snapshot.py (capture/restore), sim/eventlog.py (append-only, deterministic order), tests/test_timetravel.py — snapshot->restore->replay bit-exact. 96 tests.
