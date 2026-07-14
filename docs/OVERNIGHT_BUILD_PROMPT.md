# PIP-II Virtual Accelerator — Overnight Autonomous Build

You are an autonomous engineering agent working on **pip2va**, a PIP-II 800 MeV H⁻
linac virtual accelerator (Python, Redis-backed microservices, PyQt6 GUI, EPICS
PVA gateway, a study/automation system, and a LoRA-distilled AI expert). Your job
tonight is to build the **deterministic, interactable, automatable simulation
substrate** and as many of the features below as you can land cleanly, working
top-down through the phases. Run unattended until you finish or run out of runway.

---

## Mission / North Star

Turn "run simulation → update IOC" into a **fork-able, agent-drivable, bit-reproducible
world**: snapshot the live machine at a frame boundary → fork K branches → apply
different setpoints → run each forward **deterministically with shared random
numbers** → compare outcomes → commit the winner or roll back. Determinism is the
substrate that makes testing, time-travel, and automated optimization all tractable.

The guiding invariant everywhere: **the content of pulse N is a pure function of
(settings snapshot at N, N) — wall-clock governs only *presentation timing*,
`pulse_id` governs *content*, and randomness is a stateless function of
`(seed, pulse_id, entity, channel)`, never a stateful stream.**

---

## Operating Rules (READ FIRST — non-negotiable)

1. **Branch.** Create and work on a git branch `overnight-build` (or a worktree).
   Never work on `main` directly.
2. **Keep the tree green.** The suite is `./.venv/bin/python -m pytest tests/ -q`
   (currently **89 passing**). It must stay green after every phase. Add new tests
   for every feature; never delete a passing test to make progress.
3. **Commit per phase**, with clear messages, ending each with:
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Push at the end (and
   after each phase if the remote is reachable).
4. **The lattice YAML is the source of truth.** `scripts/gen_lattice.py` is STALE and
   will silently clobber `pip2va/lattice/pip2_lattice.yaml` if run — **do NOT run it.**
   Edit the YAML directly (it round-trips through `yaml.safe_dump(sort_keys=False,
   width=100)`, so load→modify→dump gives surgical diffs).
5. **Never commit model weights.** `scripts/distill/merged*`, `*.gguf`, `out*/` stay
   out of git. Check `.gitignore`; do not add large binaries.
6. **Everything new is additive / behind fallbacks.** Do not change existing runtime
   behavior unless a phase explicitly says to. New determinism paths sit behind the
   existing `rng or default_rng()` fallbacks and feature flags in
   `pip2va/common/config.py` (default them to the current behavior).
7. **Don't block on Docker.** Verify with the venv test suite. Only do a full
   `docker compose up -d --build` in the final verification phase (images bake code
   via `COPY pip2va`, so a rebuild is needed to run services, but tests don't need it).
8. **If a phase is blocked or too risky, SKIP it, leave the tree green, and log why.**
   Do not leave broken code. Prefer shipping Phases 1–4 solid over half-landing 1–10.
9. **Log progress continuously** to `docs/OVERNIGHT_PROGRESS.md` (append a timestamped
   line per meaningful step + per phase: what you did, tests status, commit hash).
10. Write focused files that match surrounding style. No placeholder/TODO code.

Priorities if runway is short: **Phase 1 > 2 > 3 > 4 > 7 > 6 > 8 > 9 > 5.**
Phases 1–4 are the substrate and matter most. Phase 5 (full DES kernel) is the big
stretch — attempt only if 1–4 are solid and tested.

---

## Context: current architecture (verify against the code, don't trust this blindly)

- **Timing service** (`pip2va/services/timing/main.py`) publishes `pulse.tick` with a
  monotonic `pulse_id` via absolute-deadline scheduling; supports pause/step (DVR).
- **Services** subscribe to ticks via `pip2va/services/base.py` `on_tick(pulse_id)`:
  `beam_physics`, `rf_sim`, `magnet_sim`, `diag_sim`, `mps`, `autotune`, plus the
  EPICS `epics_gateway`/`epics_ws`. `dt = 1.0/tick_hz` is already a **constant**
  (good — don't regress that).
- **Physics**: `pip2va/physics/envelope.py` (authoritative per-pulse 6×6 σ-matrix,
  CPU, deterministic), `pip2va/physics/macro.py` (GPU cupy tracker — decoupled,
  non-authoritative; keep it that way), `pip2va/physics/injection.py` (score 0–100),
  `pip2va/physics/losses.py`, `pip2va/physics/maps.py`.
- **RNG today**: seeded with fixed constants but as **stateful streams**
  (`magnet_sim` 2026, `diag_sim` 20260703, `beam_physics` 77, `macro` 12345);
  `devmodel.py:22` and `diag_sim/waveforms.py:32` have entropy fallbacks. This is the
  core thing Phase 1 fixes.
- **DVR**: telemetry ring buffers (`stream_maxlen=100`, 5 s at 20 Hz), `state:sim.run`
  / `state:sim.step`, `DataHub.seek(offset)` in `pip2va/gui/datahub.py`.
- **Study/automation**: `pip2va/analysis/studies.py`, `study_presets.py`,
  `knowledge.py` (KB findings/insights), `assistant.py` (AI), `codebase.py` (code-RAG).
- **Lattice**: `pip2va/lattice/pip2_lattice.yaml` (arc-straight-arc BTL, 217°, SAD/BAL
  dump branches in `Lattice.branches`, loaded by `pip2va/common/lattice.py`).

---

## PHASE 1 — Deterministic core (FOUNDATION, do this first & thoroughly)

**Goal:** every stochastic value is a pure function of `(GLOBAL_SEED, pulse_id,
entity_id, channel)`. Reproducibility no longer depends on execution history,
restarts, or ordering.

1. **`pip2va/common/rng.py`** — counter/hash-based RNG:
   - `pulse_rng(*keys) -> np.random.Generator` built from
     `np.random.default_rng(np.random.SeedSequence([GLOBAL_SEED, *hashed_keys]))`,
     where string keys hash to stable ints (e.g. `zlib.crc32`). Pure function of keys.
   - `GLOBAL_SEED` from `Settings` (`config.py`), default fixed (e.g. `0xB00B5`).
   - Helpers: `noise(pulse_id, entity, channel, size=None)` convenience wrappers.
   - Docstring: explain "counter-based (Philox/Random123 style), not a stream" and why
     (survives restarts, ordering, and enables Common Random Numbers across branches).
2. **Retrofit all noise sources** to derive their generator per-pulse from `pulse_rng`:
   `common/devmodel.py` (drift+ripple), `services/diag_sim/waveforms.py` (BPM/BLM/
   toroid noise), `services/rf_sim/cavity_model.py` (microphonics/He/lines/bursts —
   key by cavity name + pulse), `services/magnet_sim`, `services/timing/utilities.py`,
   and `physics/macro.py` particle init (key by pulse_id). Keep old constructor args
   working (fallback), but when a `pulse_id` is available, seed from it.
3. **Audit for wall-clock leaks into physics.** Any `time.time()`/`monotonic()` feeding
   a *value* (not scheduling) is a bug — route it through logical time
   (`pulse_id / tick_hz`). Leave heartbeats/scheduling on wall-clock.
4. **Single-process synchronous driver** `pip2va/sim/driver.py`:
   `sim_step(state, pulse_id, snapshot) -> readouts` runs the stages in a fixed order
   (timing→magnet→rf→beam→diag→mps), no Redis, no threads, same physics code. This is
   the deterministic execution model for tests and (later) branching.
5. **Golden-master test** `tests/test_determinism.py`:
   - Run the driver over a scripted input sequence (setpoint changes at known pulses)
     for ~200 pulses, twice, assert **bit-exact** equality of the full readout stream.
   - A second test: run it, perturb one setpoint at pulse 100, assert everything before
     100 is byte-identical (causality/isolation).
   - Store a hashed golden trace under `tests/golden/` and assert against it (regen
     helper gated behind an env var).
   - Pin FP: set `OMP_NUM_THREADS=1` in the test (and document it).

**Gate:** all existing tests + new determinism tests green; two runs bit-identical.

---

## PHASE 2 — Snapshot / time-travel

**Goal:** cheap, consistent whole-state checkpoints at frame boundaries; deterministic
replay.

1. **`pip2va/sim/snapshot.py`** — capture/restore full sim state at a frame boundary:
   all settings hashes, device internal state (drift accumulators, RF ring/tuner state,
   integrator state), and `pulse_id`. Serialize compactly (msgpack/JSON+arrays).
   Prefer structural sharing / copy-on-write where cheap.
2. **Event-sourced history**: an append-only event log (`pip2va/sim/eventlog.py`) of
   input events (setpoint writes, trips) keyed by `(pulse_id, seq)`. Generalize the DVR
   from telemetry-ring to **checkpoint + event log** so any past frame is reconstructable
   by `restore(checkpoint) then replay(events)`.
3. **Deterministic replay test**: snapshot at pulse A, run to B recording outputs,
   restore A, replay to B, assert bit-identical. Add to `tests/test_determinism.py`.
4. Wire into the existing DVR: `DataHub.seek` and the timing pause/step should be able
   to restore a real snapshot (not just scrub telemetry) when available.

**Gate:** snapshot→restore→replay is bit-exact; existing DVR still works.

---

## PHASE 3 — Interactivity: commit-horizon input

**Goal:** operators/agents inject setpoints at arbitrary real times, but application is
deterministic and replayable.

1. **`pip2va/sim/input.py`** — an input injector: external commands become **timestamped
   events quantized to a commit horizon** `N+k` (k from config, default small). All
   setpoint writes route through it → the event log.
2. Route GUI/EPICS/study setpoint writes through the injector (keep a direct path behind
   a flag for compatibility). Document the latency-budget tradeoff (rollback-netcode/GGPO
   analogy) in the module docstring.
3. Test: interleave scripted inputs at odd virtual times; assert the resulting trace is
   identical across two runs and matches a replay from the event log.

**Gate:** interactive input is deterministic and replayable.

---

## PHASE 4 — Branch / what-if engine (the payoff)

**Goal:** fork K deterministic branches from one snapshot, evaluate setpoint deltas with
**Common Random Numbers**, compare.

1. **`pip2va/sim/branch.py`** — `fork(snapshot, [setpoint_deltas], n_pulses) ->
   [BranchResult]`. Each branch restores the snapshot, applies its delta via the input
   injector, runs the driver `n_pulses` forward. **All branches share identical RNG keys**
   (CRN) so outcome differences are pure signal from the delta, not noise.
2. **Parallel execution** respecting data dependencies: branches are independent, so run
   them across processes/cores (multiprocessing pool). Within a branch, keep the fixed
   stage order. Document that determinism holds because branches can't observe each
   other's ordering (partial-order / DAG argument).
3. A clean **action/observation API**: `evaluate(setpoints) -> metrics`
   (transmission, worst_blm, injection score, emittance, orbit_rms, …) for automation.
4. Tests: (a) CRN — two branches with the *same* delta produce identical outputs;
   (b) isolation — a branch never mutates the parent snapshot; (c) parallel == serial
   (running branches in a pool matches running them sequentially, bit-exact).

**Gate:** branch fork/compare is deterministic, CRN-correct, and parallel-safe.

---

## PHASE 6 — Automation loop (do before 5; high user value)

**Goal:** rigorous, reproducible optimization on the branch engine — starting with the
injection score the user already cares about.

1. **`pip2va/analysis/optimizer.py`** — a black-box optimizer (CMA-ES or a simple
   Bayesian/coordinate-descent; no heavy deps — implement CMA-ES compactly or use a
   pure-python approach) that drives `branch.evaluate`. CRN makes the objective smooth.
2. **Injection auto-tune** preset: optimize painting bump/decay + BTL debuncher amp/phase
   + relevant correctors to maximize `injection.score`, forked from the live snapshot.
   Persist the best config; expose "apply winner" (guarded).
3. **Sensitivity/Jacobian** via CRN finite differences: `sensitivity(setpoints, knobs)`
   returns d(metric)/d(knob) cheaply and low-variance. Useful for the GUI heatmap (Phase 9)
   and for the study planner.
4. Wire into the study system (`analysis/studies.py`): a study kind `optimize` that runs
   the optimizer and writes a KB finding.
5. Tests: optimizer improves a known-suboptimal injection config on a fixed seed,
   deterministically (same result twice).

**Gate:** injection auto-tune measurably raises the score, reproducibly.

---

## PHASE 7 — Physics realism (independent track; high value, do early if substrate stalls)

1. **Lorentz / magnetic stripping in BTL dipoles** (`physics/losses.py` + wire into
   `envelope.py` dipole handling): Keating-form `dN/ds ∝ (B/A1)·exp(-A2/(βγc·B))` for
   H⁻ in a magnetic field. Now that the arcs are real 217° at B≈0.24 T (below the
   0.277 T limit), localize this loss in the arc dipoles and feed the nearest-BLM map.
   Add a `physics` knob to scale it. Test: loss rises sharply as B→0.277 T, negligible
   at 0.24 T (matches the design margin), and lands on arc BLMs.
2. **Longitudinal dynamics** (`physics/envelope.py` or a new `physics/longitudinal.py`):
   track (φ, W) so RF bucket capture, the BTL debuncher rotation, and dp/p-at-the-foil
   are *consequences*, not inputs. Feed the real dp/p into `injection.score` (replace the
   propagated-moment approximation). Test: debuncher amp/phase actually changes dp/p and
   thus capture, monotonically.
3. **Non-Gaussian halo** option in `macro.py` init (add tails) so the loss map reflects
   halo scraping, behind a flag.
4. (Stretch) **Validation scaffolding** `scripts/validate.py`: compare envelope
   emittance/transmission/loss against the design numbers in
   `docs/research/pip2_machine_report.md`; emit a table + pass/fail on tolerances.

**Gate:** new physics is tested and does not regress existing physics tests.

---

## PHASE 8 — Observability / causal debugging

1. **Record-replay**: with the event log + snapshots, add `pip2va/sim/replay.py` to
   re-run any recorded window bit-exactly and diff two runs.
2. **Causal slicing**: given a target readout at pulse N, walk the dependency graph
   backward (which snapshot + which input events + which stage produced it) and print the
   causal chain. Requires each stage to declare/record its read/write sets (add a light
   provenance tag).
3. **Determinism CI gate**: a `make determinism` target + the golden-master test wired so
   any nondeterminism regression fails loudly. Add `code_index.npz` freshness + a
   determinism check to `scripts/health_check.sh` / `make status`.

**Gate:** a recorded bug reproduces 100%; causal slice prints a plausible chain.

---

## PHASE 9 — GUI surface for all of the above

Add pages/controls (PyQt6, follow existing `pip2va/gui/pages/` patterns; update the nav
in `gui/main.py` and the smoke test `tests/test_gui_smoke.py` nav count):
1. **Timeline / branch page**: fork from now, run K what-ifs, compare metrics side by
   side, commit a winner or roll back. Builds on the DVR playback bar.
2. **What-if / sensitivity panel**: CRN sensitivity heatmap (knob × metric) from Phase 6.
3. **Auto-tune page**: launch injection optimization, watch it converge, apply winner.
4. **Causal-debug inspector**: click a readout → show its causal slice.
5. A small **determinism indicator** in the banner (green when the golden master matches).

**Gate:** GUI imports/builds, smoke test passes, no 3D mesh warnings regress.

---

## PHASE 5 — Full DES kernel (BIG STRETCH — only if 1–4,6,7 are solid)

Prototype a variable-timestep discrete-event kernel to replace the fixed 20 Hz tick for
multi-rate efficiency, WITHOUT breaking determinism:
1. **`pip2va/sim/kernel.py`** — a priority queue of events ordered by **superdense time**
   `(t_virtual, priority, source_id, seq)` (the total-order tie-break is what keeps
   batching deterministic). Pop earliest, batch all events at equal `t_virtual`, apply
   commutative-reduction events together and non-commutative ones in sorted order.
2. **Multi-rate**: let subsystems schedule their own next event — RF/LLRF at 2.5 µs
   (currently a 220-step inner loop), microphonics at ~60 s, drift at ~30 min, pulses at
   20 Hz, trips as scheduled Poisson events. Port **rf_sim first** as the proof (its
   intra-pulse loop is the natural fit).
3. **Conservative PDES** only (no speculative rollback). Multi-core via the dependency
   DAG: declare read/write sets, run non-conflicting events concurrently, reserve the
   `(source, seq)` tie-break for genuine write-conflicts.
4. Keep the fixed-tick path working; the kernel is opt-in behind a flag. Golden masters
   must still pass through the kernel path.

**Gate:** kernel reproduces the fixed-tick golden master bit-exact for at least the RF
subsystem; multi-rate scheduling demonstrably skips idle intervals.

---

## Cross-cutting features to fold in wherever they fit (bonus, as time allows)

- **Per-run manifest** (`pip2va/sim/manifest.py`): GLOBAL_SEED, git SHA, lattice hash,
  config → written next to any golden/branch run for provenance.
- **`make_insights.py`** (`scripts/distill/`): the missing insight generator — feed the
  LLM batches of raw KB findings grouped by section/device, propose candidate
  `MACHINE CONSTRAINT:` insights with cross-references, **human-gated** append
  (`--apply`). Closes the "insights aren't reproducible" gap. (See the AI-architecture
  discussion: insights are currently hand-authored with no in-repo generator.)
- **Reproducible dataset build**: seed `make_dataset.py`'s teacher paraphrases + add a
  semantic guard (embed q1 vs q0 with `qwen3-embedding:8b`, keep only cos > ~0.8) so
  drifted rewrites are dropped and rebuilds are stable.
- **EPICS multicast fix**: pin the server-side multicast to the interface in the
  `x-epics-env` anchor (`EPICS_PVAS_INTF_ADDR_LIST` / `EPICS_PVAS_BEACON_ADDR_LIST` /
  CAS equivalents → `239.128.1.6,8@${EPICS_HOST_INTERFACE}` etc.) so discovery survives
  container recreation. Parameterized on `${EPICS_HOST_INTERFACE}`, safe for both hosts.
- **Fast-forward mode**: run the deterministic driver faster than real-time for agent
  rollouts (decouple sim rate from wall-clock).
- **Config flags** in `config.py` for every new subsystem, defaulting to current behavior.
- **Docs**: a `docs/guides/08-determinism-and-branching.md` explaining the model
  (logical time, counter RNG, CRN, snapshots, commit horizon, branching, DES kernel).

---

## Final phase — verify, document, report

1. Run the **full test suite**; it must be green (report the count — should be ≥ 89 + new).
2. Do one **`docker compose up -d --build`** and confirm all services come up and the
   pulse advances (physics alive) with no tracebacks in `docker compose logs`.
3. Update **`MEMORY.md`** / add memory files for anything non-obvious you discovered.
4. Write **`docs/OVERNIGHT_REPORT.md`**: what landed per phase, what was skipped and why,
   test counts, commit hashes, and a prioritized "next session" list.
5. Push the branch. Do **not** merge to `main` — leave that for the user to review.
   Print the branch name and a one-paragraph summary as your final message.

Work methodically, keep the tree green, log as you go, and prefer depth over breadth.
Good luck — build something the user wakes up excited about.
