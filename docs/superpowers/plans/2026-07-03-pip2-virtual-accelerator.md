# PIP-II Virtual Accelerator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dockerized microservice simulation of the Fermilab PIP-II 800 MeV H⁻ linac running at 20 Hz with a native PyQt6 control-room GUI.

**Architecture:** Six services (timing, beam-physics [GPU], rf-sim, magnet-sim, diag-sim, mps) communicate through Redis pub/sub + streams, all keyed by pulse ID. A YAML lattice file is the single source of truth. beam-physics runs a CUDA envelope pass every pulse and a rolling macroparticle pass; diag-sim converts ground truth into noisy measurements the GUI consumes.

**Tech Stack:** Python 3.11+, CuPy (fallback NumPy), redis-py, msgpack, PyYAML, pydantic, PyQt6, pyqtgraph, Docker Compose (ARM64, nvidia-container-toolkit), pytest.

## Global Constraints

- Target: NVIDIA DGX Spark (aarch64, GB10). Docker images must be linux/arm64. GPU only in `beam-physics` (NGC CUDA base image).
- All array payloads on Redis are msgpack-encoded `{"pulse_id": int, "data": {name: [floats]}}`; float32 lists.
- Physics engine must run with NumPy when CuPy/GPU unavailable (`PIP2VA_BACKEND=numpy|cupy`, auto-detect default) — CI and unit tests run CPU-only.
- Package name `pip2va`, installable with `pip install -e .`; GUI entry point `pip2va-gui`.
- Streams capped at MAXLEN≈1200. Redis exposed on host port 6379.
- 20 Hz tick period = 50 ms; envelope pass budget ≤ 15 ms.
- H⁻ rest mass 939.294 MeV; bunch frequency 162.5 MHz; nominal current 2 mA; pulse length 0.55 ms.

---

### Task 1: Repo scaffold + `common` package (keys, codec, config)

**Files:**
- Create: `pyproject.toml`, `README.md`, `.gitignore`, `pip2va/__init__.py`
- Create: `pip2va/common/__init__.py`, `pip2va/common/keys.py`, `pip2va/common/codec.py`, `pip2va/common/config.py`
- Test: `tests/test_codec.py`, `tests/test_keys.py`

**Interfaces:**
- Produces: `keys.stream(product) -> "stream:{product}"`, `keys.settings(cls, name)`, `keys.readback(cls, name)`, `keys.truth(name)`, channel constants `CH_TICK="pulse.tick"`, `CH_SETTINGS="settings.changed"`, `CH_MPS="mps.trip"`, `CH_FAULT="device.fault"`.
- Produces: `codec.pack(pulse_id:int, data:dict[str, list|np.ndarray]) -> bytes`, `codec.unpack(bytes) -> (pulse_id, dict[str, np.ndarray(float32)])` (msgpack; ndarray values sent as raw float32 bytes + shape).
- Produces: `config.Settings` (pydantic-settings): `redis_url` (default `redis://localhost:6379/0`), `backend` (`auto|numpy|cupy`), `tick_hz=20.0`, `stream_maxlen=1200`.

- [ ] Steps: write failing tests for codec round-trip (ndarray and list input, float32 out, pulse_id preserved) and key formatting → run (fail) → implement → run (pass) → `git commit -m "feat: scaffold repo and common package"`.

### Task 2: Lattice definition + loader

**Files:**
- Create: `pip2va/lattice/pip2_lattice.yaml` (full machine), `pip2va/common/lattice.py`
- Test: `tests/test_lattice.py`

**Interfaces:**
- Produces: `load_lattice(path=None) -> Lattice`; `Lattice.elements: list[Element]`; `Element` (pydantic): `name, type, s (m, entrance), length, section`, type-specific params dict, `aperture_radius`, optional `knobs: dict[str, str]` (knob → settings hash key). `Lattice.instruments(type)` returns ordered instruments with `s` positions. Types: `drift, solenoid, quad, corrector, rfgap, rfq, chopper, aperture, bpm, blm, toroid, wire_scanner, source`.

Lattice content (refined by research report where published values exist; else these baselines):
- LEBT: source(30 keV) + 3 solenoids + chopper, ~2.0 m. RFQ: lumped, 162.5 MHz, out 2.1 MeV, 4.4 m.
- MEBT ~10 m: 9 quads, 3 bunchers (162.5 MHz), chopper+absorber, 2 toroids, 4 BPMs, 2 wire scanners.
- HWR: 8 cav @162.5 MHz alternating with 8 solenoids (2.1→10.3 MeV, ~6 m).
- SSR1: 16 cav @325 MHz + 8 solenoids (→ ~35 MeV, ~10 m). SSR2: 35 cav @325 MHz + solenoids per CM (→ ~185 MeV, ~23 m).
- LB650: 36 cav @650 MHz, quad doublets between CMs (→ ~516 MeV). HB650: 24 cav @650 MHz (→ ~800 MeV). BTL: 2 dipole bends + quads + BPMs to endpoint.
- BPM adjacent to every solenoid/doublet (~50); BLM every ~3 m in SC linac (~45); toroid at each section boundary (8); x/y corrector pair at every solenoid/doublet (~40 pairs). Each cavity knob keys: `settings:rf:{name}` fields amp (MV), phase (deg); magnets: `settings:magnet:{name}` field current (A) with linear field calibration in params.

- [ ] Steps: failing tests (monotonic s, energy checkpoints stored in section metadata, ≥45 BPMs+BLMs, every knob key well-formed) → implement YAML + loader → pass → commit.

### Task 3: Physics core — kinematics + transfer maps

**Files:**
- Create: `pip2va/physics/__init__.py`, `pip2va/physics/backend.py` (xp = cupy|numpy selection), `pip2va/physics/kinematics.py`, `pip2va/physics/maps.py`
- Test: `tests/test_maps.py`

**Interfaces:**
- Produces: `kinematics.beta_gamma(W_MeV) -> (beta, gamma)`; `maps.drift(L, beta, gamma) -> 6x6`; `maps.quad(L, k1)`; `maps.solenoid(L, Bz, brho)`; `maps.rfgap_kick(W_in, V_MV, phi_deg, freq) -> (W_out, M6, dphase)` using dW = q·V·T·cos(φ) and Panofsky transverse defocusing `k_rf = -π·V·T·sin(φ)/(m·β²γ³·λ)` distributed as a thin lens in x, y and longitudinal focusing in (z, δ); `maps.corrector_kick(angle_x, angle_y)` additive to centroid.
- Coordinates: state vector (x, x', y, y', z, δ=Δp/p); centroid 6-vector + 6×6 sigma matrix.

- [ ] Steps: failing analytic tests (drift grows σx correctly; thick quad vs thin-lens limit; solenoid rotates x→y at the Larmor angle; on-crest gap: energy gain = V·T, no transverse kick; off-crest sign of defocusing) → implement → pass → commit.

### Task 4: Envelope engine + space charge + losses

**Files:**
- Create: `pip2va/physics/envelope.py`, `pip2va/physics/losses.py`
- Test: `tests/test_envelope.py`

**Interfaces:**
- Produces: `EnvelopeEngine(lattice, backend)` with `.run(device_state: DeviceState, current_mA, beam_on) -> EnvelopeResult`. `DeviceState` = dict-like readbacks `{element_name: {field: value}}`. `EnvelopeResult`: arrays over element index — `s, W, centroid(x,y), sigma(x,y,z), phase, transmission, loss_W_per_m`, plus per-instrument samples `at_bpms (x,y,phase,sum)`, `at_blms (loss)`, `at_toroids (I)`.
- Space charge: linear KV defocus per slice, perveance from current & (βγ); one iteration. Losses: per-element Gaussian tail fraction `erfc((a−|c|)/(√2·σ))` per plane × transported beam power, + H⁻ baselines (intrabeam stripping ∝ I²/(βγ)³·density heuristic, residual gas constant/m), converted to W/m and BLM signals with 1/r² smearing to nearest BLMs.
- Performance: full pass as chained batched matmuls on backend `xp`; must complete < 15 ms on GPU, < 50 ms NumPy on dev box.

- [ ] Steps: failing tests (zero-current drift-quad FODO matches periodic solution; full lattice on design settings reaches 800±25 MeV with ≥99% transmission; scaled-up corrector produces proportional BPM offset; aperture scrape produces localized loss) → implement → pass → benchmark script `scripts/bench_envelope.py` prints ms/pass → commit.

### Task 5: Macroparticle tracker

**Files:**
- Create: `pip2va/physics/macro.py`
- Test: `tests/test_macro.py`

**Interfaces:**
- Produces: `MacroTracker(lattice, n=100_000, backend)` with `.run(device_state, current_mA) -> MacroResult`: alive mask, per-wire-scanner 1D profiles (x and y histograms, 64 bins), phase-space snapshots (x-x', y-y', z-δ; 2D 64×64 histograms) at section boundaries, rms emittances vs s, particle loss map (per element count → W/m). Same maps as Task 3 applied per-particle (exact phase-dependent RF kick per particle), aperture culling, 2.5D space-charge kick every element slice using r.m.s.-Gaussian E-field approximation.

- [ ] Steps: failing tests (matched Gaussian beam through FODO conserves rms emittance to 1%; macro energy profile matches envelope W(s) within 1%; particles beyond aperture are removed and counted) → implement → pass → commit.

### Task 6: Service framework + timing service

**Files:**
- Create: `pip2va/services/base.py` (Service class: redis conn, pubsub loop, graceful shutdown, `on_tick(pulse_id)` hook, XADD helper with maxlen), `pip2va/services/timing/main.py`
- Test: `tests/test_timing.py` (uses `fakeredis`)

**Interfaces:**
- Produces: `Service` base — subclasses implement `on_tick`; helper `.publish_stream(product, pulse_id, data)`. timing publishes `CH_TICK` message `{"pulse_id": n, "t": monotonic}` at `tick_hz` with drift-free scheduling (sleep to absolute deadline), and XADDs `stream:timing.tick`.

- [ ] Steps: failing tests (tick messages monotonic pulse_id; measured rate 20±1 Hz over 1 s with fakeredis + patched clock) → implement → pass → commit.

### Task 7: magnet-sim + rf-sim services

**Files:**
- Create: `pip2va/services/magnet_sim/main.py`, `pip2va/services/rf_sim/main.py`, `pip2va/common/devmodel.py` (shared first-order device dynamics: slew-limited approach to setpoint, ripple, drift, trip state machine)
- Test: `tests/test_devsims.py`

**Interfaces:**
- Consumes: lattice knobs; `settings:*` hashes; `CH_TICK`, `CH_SETTINGS`.
- Produces: per tick, readback hashes `readback:magnet:{name}` `{current, field}` / `readback:rf:{name}` `{amp, phase, detuning_hz, forward_pw, status}` and streams `stream:magnet.readback`, `stream:rf.cavity`. rf-sim adds microphonics (sum of 3 sinusoids + noise), Lorentz-force detuning ∝ amp², slow tuner servo pulling detuning→0, quench model (amp above quench_limit or injected fault ⇒ status=tripped, amp→0, publishes `CH_FAULT`). magnet-sim: RL-type slew (τ per family), ppm-level ripple, thermal drift, trip on injected fault.
- Fault injection contract (used by mps + GUI): hash `fault:{class}:{name}` fields (`type`: trip|drift|detune|noise, `magnitude`, `ttl`).

- [ ] Steps: failing tests (setpoint step slews exponentially, readback ripple σ within spec, quench trips and requires explicit reset field `reset=1` in settings hash) → implement → pass → commit.

### Task 8: beam-physics service

**Files:**
- Create: `pip2va/services/beam_physics/main.py`
- Test: `tests/test_beam_service.py`

**Interfaces:**
- Consumes: `CH_TICK`; `readback:*` hashes (bulk `MGET`-style pipeline read → `DeviceState`); `state:mps.permit`; source settings (`settings:source:main` current_mA, `settings:chopper:main` duty).
- Produces: `truth:beam` hash (packed EnvelopeResult), `state:beam` summary hash (W_out, transmission, permit, pulse_id, lag_ms), and kicks a persistent MacroTracker thread that free-runs and writes `stream:beam.deep` (packed MacroResult) after each pass. Beam permit false ⇒ runs with beam_on=False (zero charge; instruments will read noise floor).

- [ ] Steps: failing tests with fakeredis (tick in → truth written same pulse_id; permit false → transmission 0; missing readback reuses previous snapshot and flags `stale=1`) → implement → pass → commit.

### Task 9: diag-sim + mps services

**Files:**
- Create: `pip2va/services/diag_sim/main.py`, `pip2va/services/mps/main.py`
- Test: `tests/test_diag_mps.py`

**Interfaces:**
- diag-sim consumes `truth:beam` (+ latest `stream:beam.deep`), applies per-instrument noise/offset/scale (from lattice params, e.g. BPM σ=30 µm at nominal charge growing as 1/√charge, toroid 0.2% + 5 µA floor, BLM 5% + dark current), publishes `stream:bpm.orbit`, `stream:blm.losses`, `stream:toroid.current`, `stream:profile.scan` (wire data on demand — a wire scan request hash `req:wire:{name}` triggers a simulated scan sequence over ~30 pulses).
- mps consumes `stream:blm.losses` + `CH_FAULT`: rolling 10-pulse mean loss per BLM > threshold (from lattice, default 1 W/m warn 0.1) ⇒ set `state:mps.permit=0`, XADD `stream:mps.events`, publish `CH_MPS`. Reset via `settings:mps:main reset=1` only when condition cleared. Manages fault-injection: applies `fault:*` requests to target device hashes with TTL.

- [ ] Steps: failing tests (orbit stream matches truth ± noise stats; loss over threshold trips permit within 10 pulses; reset blocked while loss persists) → implement → pass → commit.

### Task 10: Docker + compose

**Files:**
- Create: `docker/base.Dockerfile` (python:3.11-slim arm64 + pip2va), `docker/beam-physics.Dockerfile` (nvcr.io/nvidia/cuda arm64 base + cupy), `docker-compose.yaml`, `.dockerignore`, `Makefile` (`make up`, `make gui`, `make test`)
- Test: `scripts/smoke_compose.py`

**Interfaces:**
- compose services: redis (port 6379 exposed), timing, beam-physics (`deploy.resources.reservations.devices` nvidia gpu, falls back via `PIP2VA_BACKEND=numpy` if unavailable), rf-sim, magnet-sim, diag-sim, mps. All get lattice via the installed package. Healthchecks: redis-cli ping; services publish `hb:{service}` heartbeat key with 5 s TTL.

- [ ] Steps: write smoke script (connects to redis, asserts all 6 heartbeats present, `stream:bpm.orbit` advances ≥15 entries/s, magnet setpoint change moves mean BPM x) → `docker compose up -d --build` → run script (pass) → commit.

### Task 11: GUI shell + data layer

**Files:**
- Create: `pip2va/gui/main.py` (entry `pip2va-gui`), `pip2va/gui/datahub.py`, `pip2va/gui/theme.py`, `pip2va/gui/widgets.py` (LED, section strip, param table row)
- Test: `tests/test_gui_smoke.py` (pytest-qt, offscreen)

**Interfaces:**
- `DataHub(QThread)`: owns redis; XREAD-follows all streams + pubsub; emits Qt signals `orbit(pulse_id, dict)`, `losses(...)`, `rf(...)`, `magnets(...)`, `toroids(...)`, `deep(...)`, `mpsEvent(...)`, `tick(pulse_id)`; provides `set_setting(cls, name, field, value)` (HSET + publish `CH_SETTINGS`) and `history(product, n)` (XREVRANGE backfill). Pages receive the hub; never import redis.
- Main window: dark control-room theme, left nav (9 pages), status bar with pulse ID, beam permit LED, W_out, transmission; pages lazy-constructed.

- [ ] Steps: failing smoke test (window constructs offscreen; DataHub against fakeredis emits orbit signal when stream entry added; set_setting writes hash) → implement → pass → commit.

### Task 12: GUI pages (one commit per page)

**Files:** `pip2va/gui/pages/{overview,instrumentation,orbit,losses,magnets,rf,profiles,source,mps}.py`; extend `tests/test_gui_smoke.py` (each page constructs + consumes one synthetic signal).

Page specs:
1. **overview** — horizontal machine strip (sections colored by health), live W(s) sparkline, transmission, permit LED, big numbers; section click → nav.
2. **instrumentation** — toroid strip charts, per-section transmission bars, device health grid (rf/magnet status from streams).
3. **orbit** — x/y/phase vs s scatter+line from `orbit` signal at 20 Hz (pyqtgraph, no per-frame allocation), reference save/diff, rms readouts.
4. **losses** — BLM bar chart vs s with 0.1/1.0 W/m lines + waterfall history plot; integration window spinbox.
5. **magnets** — tree by section; per element: setpoint spin, readback label, trim ±; bulk zero-correctors button.
6. **rf** — cavity table (amp, phase, detuning, status LED) per section tab; detail pane: detuning history plot, tuner controls, phase/amp sliders, reset button.
7. **profiles** — wire scanner selector + scan trigger (writes `req:wire`), profile plot with Gaussian fit overlay; phase-space image panels from `deep` signal.
8. **source** — source current dial, LEBT solenoid controls, chopper duty editor with pulse-shape preview.
9. **mps** — permit tree per section, `stream:mps.events` trip log table, reset button; "Fault Injection" tab (device picker, fault type, magnitude, apply) gated behind an "Expert" toggle.

- [ ] Steps per page: failing construct+signal smoke test → implement page → pass → commit (`feat(gui): <page> page`).

### Task 13: End-to-end validation + docs

**Files:**
- Create: `scripts/e2e_check.py`, update `README.md` (quickstart: `docker compose up -d`, `pip install -e .[gui]`, `pip2va-gui`; architecture diagram; page screenshots list)
- Test: run `scripts/e2e_check.py` against live compose stack.

- [ ] Steps: e2e script asserts — 20 Hz sustained 30 s (≥580 pulses), envelope lag_ms p95 < 50, corrector step visibly moves orbit stream, injected cavity trip drops W_out and MPS trips on resulting loss, reset restores beam → fix anything that fails → update README → commit.

## Self-Review Notes

- Spec coverage: services (T6–T9), physics (T3–T5), Redis schema (T1, T6–T9), docker (T10), all 9 GUI pages (T11–T12), realism+MPS+fault injection (T7, T9, page 9), error handling (T8 stale snapshot, T6 shutdown, hub reconnect), testing section (unit per task + T13 e2e). Lattice research lands in T2.
- Types consistent: `DeviceState`, `EnvelopeResult`, `MacroResult`, codec contract, key module shared everywhere.
