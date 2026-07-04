# PIP-II Virtual Accelerator — Design Spec

**Date:** 2026-07-03
**Status:** Approved (user approved Sections 1–3 explicitly and delegated remaining sections to recommended design)

## 1. Purpose

A virtual accelerator simulating the Fermilab PIP-II 800 MeV H⁻ superconducting linac: the full lattice (LEBT → RFQ → MEBT → HWR → SSR1 → SSR2 → LB650 → HB650 → BTL) with instrumentation, RF, and magnet power supplies, running at the machine's 20 Hz pulsed rate. A PyQt6 control-room GUI provides operator pages per subsystem. The system behaves like a real machine: the GUI only sees noisy "measured" data, devices drift and trip, and an MPS governs beam permit.

**Target platform:** NVIDIA DGX Spark (GB10, aarch64). Backend in Docker with GPU passthrough (nvidia-container-toolkit, ARM64 images); GUI runs natively on the host.

## 2. Architecture — services (approved)

Docker Compose backend of 6 microservices + Redis, one service per subsystem:

| Service | Role | GPU |
|---|---|---|
| `timing` | 20 Hz master clock; publishes `pulse.tick` with monotonic pulse ID | no |
| `beam-physics` | CUDA envelope pass each pulse + rolling GPU macroparticle tracking; publishes ground-truth beam state | **yes** |
| `rf-sim` | Per-cavity dynamics: LLRF amplitude/phase loops, microphonics + Lorentz-force detuning, slow tuner/piezo, quenches/trips | no |
| `magnet-sim` | Power supplies: setpoint slewing, ripple, warm-up drift, trips; publishes readback currents/fields | no |
| `diag-sim` | Samples ground truth at instrument locations, applies noise/calibration/offsets, publishes measurements | no |
| `mps` | Loss/device-state watchdog, beam permit latching, trip history, fault-injection API | no |

GUI (PyQt6 + pyqtgraph) connects to Redis on an exposed port. `docker compose up` launches the backend; a `make gui` / `pip install -e . && pip2va-gui` entry point launches the GUI on the host.

## 3. Data flow & Redis schema (approved)

Everything keyed to the **pulse ID** stamped by `timing`.

- **Pub/Sub** — `pulse.tick` heartbeat; async events `mps.trip`, `device.fault`, `settings.changed`.
- **Streams** (capped `MAXLEN ~1200` ≈ 1 min) — one stream per data product, one `XADD` per pulse containing msgpack-packed arrays: `stream:bpm.orbit` (x, y, phase, intensity per BPM), `stream:blm.losses`, `stream:toroid.current`, `stream:rf.cavity` (amp/phase/detuning per cavity), `stream:magnet.readback`, `stream:beam.deep` (slow macroparticle products), `stream:mps.events`.
- **Hashes** — `settings:{class}:{name}` (GUI-written setpoints), `readback:{class}:{name}`, `state:beam`, `truth:beam` (ground truth; GUI never reads it), `lattice:elements` (static, loaded at startup).

Setting change flow: GUI writes hash → publishes `settings.changed` → owning sim service slews readback toward setpoint realistically → beam-physics reads *readbacks* (not setpoints) each pulse.

Per-pulse cycle within the 50 ms budget: tick → rf-sim/magnet-sim update device state (~2 ms) → beam-physics envelope pass (~10–15 ms) → diag-sim samples + XADDs (~3 ms) → mps evaluates permit. All services read the same device-state snapshot per pulse ID.

## 4. Physics engine (approved)

**Lattice file.** One YAML file defines every element in order (drifts, solenoids, quads, dipole correctors, RF gaps, apertures, instrument locations) with physics parameters and Redis knob keys. Single source of truth for all services and the GUI. Generated from published PIP-II lattice data (background research report; numbers marked approximate where not published).

**Envelope pass (every pulse, CUDA/CuPy).** 6×6 transfer-matrix transport of centroid + 6D sigma matrix, matrices rebuilt each pulse from live readbacks. RF gaps: thin-gap Panofsky energy kick + transverse RF defocusing + phase-slip tracking; RFQ lumped. Linear KV-equivalent space-charge defocusing from the envelope, iterated once. Losses = Gaussian tail fraction outside apertures + H⁻ baselines (intrabeam stripping ∝ density, residual-gas stripping), distributed to nearby BLMs.

**Macroparticle pass (rolling, CUDA/CuPy).** ~100k particles, same element maps plus exact phase-dependent RF kicks, real aperture collimation, 2.5D space-charge kicks. Free-runs (~0.2–1 s per full pass); publishes wire-scanner profiles, phase-space snapshots, emittances, particle-true loss map that diag-sim blends with the envelope estimate.

## 5. Machine model — lattice summary

Baseline PIP-II parameters (refined by research report; approximate where noted):

- H⁻, 2 mA nominal, 162.5 MHz bunch frequency, 20 Hz × 0.55 ms pulses (Booster injection mode); CW-capable ignored except as a mode flag.
- Sections: LEBT (30 keV, ion source + 3 solenoids + chopper) → RFQ (162.5 MHz → 2.1 MeV) → MEBT (quads, 3 bunching cavities, fast chopper + absorber, scrapers) → HWR (1 CM, 8 cavities @162.5 MHz, 8 solenoids → ~10 MeV) → SSR1 (2 CM, 16 cavities @325 MHz, 8 solenoids → ~35 MeV) → SSR2 (7 CM, 35 cavities @325 MHz → ~185 MeV) → LB650 (~9 CM, ~36 cavities @650 MHz, doublet focusing → ~500 MeV) → HB650 (~4 CM, ~24 cavities @650 MHz → 800 MeV) → BTL to Booster (dipoles, quads).
- Instrumentation: BPMs (x, y, phase, intensity) distributed ~1 per focusing period (~50 total), BLMs along SC linac, toroids/ACCTs per section boundary, wire scanners in MEBT + warm regions, laserwire stations in SC linac.
- Correctors: horizontal+vertical dipole trims paired with each solenoid/quad package.
- Realism: noise+jitter, slow drifts (microphonics, thermal), faults & MPS interlocks, and an errors-on-demand fault-injection panel. Loss criterion 0.1 W/m surfaces in the loss display.

## 6. GUI (PyQt6 + pyqtgraph)

Single QMainWindow with a left nav sidebar; each page a QWidget module:

1. **Synoptic overview** — machine schematic with live energy/transmission/permit, click-through to sections.
2. **Instrumentation dashboard** — toroids, transmission, pulse charge, device health grid.
3. **Orbit viewer** — x/y/phase orbit vs s from all BPMs, live at 20 Hz, reference-orbit save/diff.
4. **Loss plots** — BLM bar/strip charts vs s, 0.1 W/m line, integration window control.
5. **Magnet trims** — table + per-element controls of correctors/quads/solenoids, setpoint vs readback.
6. **RF tuner/viewer** — per-cavity amp/phase/detuning, cavity waveform detail, tuner controls, trip status.
7. **Profiles & phase space** — wire-scanner scans and x-x′/y-y′/longitudinal phase-space from macroparticle data.
8. **Ion source & LEBT** — source current, solenoids, chopper pattern editor.
9. **MPS/fault panel** — permit tree, trip history, reset; hidden fault-injection admin tab.

GUI data layer: one background QThread owns Redis subscriptions (streams via `XREAD`, events via pub/sub) and emits Qt signals; pages never touch Redis directly. Plots throttle to display refresh; data kept at full 20 Hz.

## 7. Repo layout

```
pip2va/
  lattice/pip2_lattice.yaml       # single source of truth
  common/                          # shared: lattice loader, redis keys/codecs (msgpack), models
  services/{timing,beam_physics,rf_sim,magnet_sim,diag_sim,mps}/
  gui/                             # PyQt6 app + pages/
  docker/                          # per-service Dockerfiles (ARM64 CUDA base for beam-physics)
  docker-compose.yaml
  tests/
```

`common` is a shared Python package installed into every image and the GUI env.

## 8. Error handling & resilience

- Services are stateless w.r.t. Redis restarts: reload lattice + last settings hashes on reconnect, resubscribe.
- beam-physics missing its 50 ms deadline logs a lag counter and skips to the newest tick (no backlog).
- A pulse with missing device data reuses the previous readback snapshot (flagged stale in `state:beam`).
- GUI reconnects with backoff; pages grey out when data is stale > 1 s.
- MPS latches trips; beam permit false ⇒ beam-physics transports zero-charge pulses (diagnostics read noise floors, as in a real machine).

## 9. Testing

- Unit: transfer matrices vs analytic cases (drift, thin quad, solenoid rotation, RF gap energy gain); envelope vs known FODO/periodic solutions; loss-fraction math; codec round-trips.
- Physics regression: on-crest full-lattice pass reaches ~800 MeV within tolerance; design optics produce matched envelopes (no beat growth).
- Service integration: docker compose up on CI-less local run, scripted checks that all streams advance at 20 Hz and a magnet setpoint change moves the orbit.
- GUI: smoke test with pytest-qt (pages construct, receive synthetic signals).

## 10. Out of scope (v1)

EPICS/channel-access compatibility, CW mode physics, Booster injection modeling beyond the BTL endpoint, multi-user arbitration, historical archiver beyond the 1-minute stream retention.
