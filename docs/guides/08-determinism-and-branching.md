# Determinism & the What-If Branch Engine

The `pip2va.sim` package turns "run sim → update IOC" into a **bit-reproducible,
fork-able, agent-drivable** world. The guiding invariant:

> The content of pulse N is a pure function of **(settings snapshot at N, N)**.
> Wall-clock governs only *presentation timing*; `pulse_id` governs *content*;
> randomness is a stateless function of `(seed, pulse_id, entity, channel)`,
> never a stateful stream.

## The pieces

| Module | Role |
|---|---|
| `common/rng.py` | Counter-based RNG. `pulse_rng(*keys)` is a pure function of `(global_seed, *keys)` — Philox-style, not a stream. Survives restarts/reordering and gives **Common Random Numbers** across branches. |
| `sim/driver.py` | Single-process, Redis-free synchronous driver over the magnet devices + envelope. The deterministic execution model for tests, replay, and branching. |
| `sim/snapshot.py` | Capture/restore full frame state (pulse_id, setpoints, device slew/drift/trip, injection knobs). `restore + replay` reproduces the future bit-for-bit. |
| `sim/eventlog.py` | Append-only input log with a deterministic `(pulse_id, seq)` total order — the event-sourcing half of time-travel and the golden master. |
| `sim/input.py` | Commit-horizon injector: a command "arriving now" applies at `pulse + horizon` (rollback-netcode trick) so interactivity stays replayable. |
| `sim/branch.py` | `fork()` runs K branches from one snapshot with CRN (differences are pure signal); `evaluate()` is the action→observation API. Branches parallelize across processes. |
| `analysis/optimizer.py` | Pattern-search `maximize()` + CRN `sensitivity()` over the branch engine; `autotune_injection()`. CRN makes the objective smooth so it converges. |
| `sim/replay.py` | Record-replay + `first_divergence()` — reproduce any bug and localize the exact pulse/field where two runs split. |

## Why it works

- **Reproducibility** — pulse N's noise no longer depends on how many draws
  happened before it, so two runs over the same inputs are byte-identical
  (`make determinism`, `OMP_NUM_THREADS=1` pins FP reduction order).
- **CRN** — branches sharing `global_seed` see identical noise, so a setpoint
  delta's effect is measured against zero variance. That's why the injection
  auto-tune converges (demo: 18.5 → 67.1).
- **Time-travel** — snapshot + event log = any past frame reconstructable;
  branch = fork the timeline.

## Not yet built (see OVERNIGHT_REPORT)

Full causal slicing (read/write-set provenance), the GUI branch/what-if pages,
and the variable-timestep DES kernel (deliberately deferred — a fixed-tick
retrofit was the right first step).
