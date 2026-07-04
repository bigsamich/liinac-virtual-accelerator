# PIP-II Virtual Accelerator (pip2va)

A virtual accelerator simulating the **Fermilab PIP-II 800 MeV H⁻
superconducting linac** — full lattice, instrumentation, RF, and magnet power
supplies — running at the machine's real **20 Hz** pulse rate, with a PyQt6
control-room GUI. Built for the NVIDIA DGX Spark (aarch64 + GB10) with CUDA
acceleration, but everything falls back to NumPy on any machine.

```
LEBT → RFQ → MEBT → HWR → SSR1 → SSR2 → LB650 → HB650 → BTL
30 keV  2.1 MeV      10.3    35     185    516     800 MeV
          162.5 MHz | 325 MHz        | 650 MHz
```

711 lattice elements, 123 RF cavities, 103 magnets, 74 BPMs, 46 BLMs,
9 toroids, 14 wire/laserwire scanners — element counts, cavity voltages,
loaded Qs, synchronous-phase law, and loss physics follow the published
PIP-II baseline (see `docs/research/pip2_machine_report.md`, ~25 primary
sources).

## Quickstart

```bash
# 1. backend: 7 containers (redis + 6 sim services, GPU passthrough)
docker compose up -d --build

# 2. GUI on the host
python3 -m venv .venv
.venv/bin/pip install -e ".[gui,dev]"
.venv/bin/pip2va-gui                  # or: make gui
```

Give the MPS ~15 s after startup to capture its BLM baseline ("armed" in the
MPS event log), then you have beam.

Verify a running stack:

```bash
make smoke      # heartbeats, 20 Hz streams, orbit response
.venv/bin/python scripts/e2e_check.py   # + cavity-trip -> MPS trip -> recovery
```

## Architecture

Six microservices communicate through Redis (pub/sub for the 20 Hz tick and
events, capped streams for telemetry, hashes for settings/readbacks), all
keyed by pulse ID:

| Service | Role |
|---|---|
| `timing` | 20 Hz master clock, monotonic pulse IDs |
| `beam-physics` | **GPU.** Envelope pass every pulse (~7 ms: centroid + 6D sigma transport, phase-slip cavity physics, 3D-ellipsoid space charge with longitudinal debunching, Gaussian-tail + H⁻ stripping losses). A free-running CuPy macroparticle tracker (400k particles, nonlinear Gaussian SC kicks, ~2.9 s/pass on GB10) publishes profiles, phase space, emittance, and a particle-true loss map. |
| `rf-sim` | Per-cavity LLRF: amplitude servo, microphonics + Lorentz-force detuning, tuner servo, quench/trip latches |
| `magnet-sim` | Power supplies: slew, ripple, thermal drift, trips |
| `diag-sim` | Turns ground truth into noisy measurements (BPM/BLM/toroid/wire-scanner models) **plus intra-pulse waveforms** (1000 samples across the 0.55 ms pulse) and the trip postmortem buffer. The GUI **never** sees ground truth. |
| `mps` | Beam permit: commissioning-style BLM baseline capture (only while delivering beam) → per-monitor thresholds, latched trips, gated reset |
| `autotune` | RESCUE restore-to-design + continuous SVD orbit correction |

Setting flow: GUI writes `settings:*` hash → publishes `settings.changed` →
owning sim slews its readback realistically → `beam-physics` transports the
next pulse from *readbacks*. Trip a cavity and the beam arrives late
everywhere downstream, gaps slip off-crest, the energy profile collapses,
losses spike, and the MPS pulls the permit — the real failure cascade.

## GUI pages

Dashboard (synoptic + toroids + live orbit/loss panels; click a section to
open its dedicated view in place), Orbit (20 Hz, reference diff, corrector
usage bars), Losses (bars + waterfall vs the 0.1/1 W/m criteria), Magnets & trims,
RF (per-cavity table + detuning detail + tuner/reset), Profiles & phase
space (live wire scans, x–x′/y–y′/z–δ from the GPU tracker), Waveforms
(intra-pulse 1000-sample traces: live toroids, selectable BPM/BLM capture,
trip postmortem buffer), Source & LEBT, MPS (permit, trip log, root-cause
analysis, expert fault injector).

All plots share a control-room toolkit: crosshair cursor with readout,
visible grids, rigid auto-Y (expands instantly, shrinks only after sustained
quiet — no bouncing axes; any manual zoom locks the axis), and device-name
x-axes (MEBT:BPM01) with a per-plot toggle back to s [m]. Every setpoint is
bounded by its device limit (supply currents, corrector ±10 A, cavity quench
levels) and BPMs cannot read beyond their own bore. The Profiles page renders
a 30k-particle 3D beam cloud from the GPU tracker at any scanner station.

An always-visible banner carries the beam-permit state with **RESET PERMIT**,
**RESCUE** (autotune restores every setpoint to design, resets tripped
devices, and re-arms the permit), and an **Auto-tune orbit** toggle (SVD
orbit correction against a model-measured response matrix).

## Trip root-cause analysis

Every MPS trip triggers an instant rule-based diagnosis on the MPS page:
loss location, tripped devices upstream, active fault injections, and
recent setpoint changes from the audit trail (`stream:settings.log`).
"Deep analysis" sends the same evidence pack to a **local LLM via Ollama**
(default `qwen3.6:latest`, configurable with `PIP2VA_LLM_MODEL` /
`PIP2VA_OLLAMA_URL`) for a physics narrative with recovery steps — and falls
back to the rule-based text if the LLM is unreachable.

## Development

```bash
make test           # 73 tests: physics vs analytic results, services on fakeredis, GUI offscreen
make lattice        # regenerate pip2va/lattice/pip2_lattice.yaml + numerical re-match
.venv/bin/python scripts/bench_envelope.py
```

The lattice YAML is the single source of truth; `scripts/gen_lattice.py`
builds it from published machine parameters and `scripts/match_lattice.py`
numerically tunes all 103 focusing strengths for a loss-free design optics
(99.4% transmission at 5 mA with space charge), baking design BLM levels in
as the MPS threshold table.

Docs: design spec in `docs/superpowers/specs/`, implementation plan in
`docs/superpowers/plans/`, machine physics reference in `docs/research/`.
