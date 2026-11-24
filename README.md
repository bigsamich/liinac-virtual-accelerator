# PIP-II Virtual Accelerator (pip2va)

A virtual accelerator simulating the **Fermilab PIP-II 800 MeV H⁻
superconducting linac** and its transfer line to Booster injection: full
lattice, instrumentation, RF, magnets, vacuum, machine protection and Booster
injection, running at the machine's real **20 Hz** pulse rate. It has a PyQt6
control-room GUI (native or in a browser over noVNC), a phone page, a
Flutter web console, an **EPICS PV Access** server, and an AI assistant on a
local Ollama model. Built for the NVIDIA DGX Spark (aarch64 + GB10) with CUDA
acceleration; the physics falls back to NumPy without a GPU.

```
LEBT → RFQ → MEBT → HWR → SSR1 → SSR2 → LB650 → HB650 → BTL → ARC1 → ARC2 → BINJ
30 keV  2.1 MeV      10.3   35     185    516     800 MeV          (+ BAL absorber line)
          162.5 MHz | 325 MHz             | 650 MHz
```

The lattice (`pip2va/lattice/pip2_lattice.yaml`, version `baseline-2026-07`)
has 13 sections and 1162 elements: 131 SRF cavities (HWR 8, SSR1 16, SSR2 35,
LB650 36, HB650 36) plus MEBT bunchers and BTL debunchers, 99 quads,
40 solenoids, 33 dipoles, 105 correctors, 108 BPMs, 120 BLMs, 12 toroids,
21 wire/laserwire scanners, dual ion sources, MEBT scrapers, an Allison
scanner, and 30 pumps, 40 gauges and 44 gate valves. Device names follow
ED0011740 Rev B. Element counts, cavity voltages, loaded Qs, the
synchronous-phase law and the loss physics follow the published PIP-II
baseline (`docs/research/pip2_machine_report.md`).

## Contents

- [Quickstart](#quickstart)
- [Interfaces](#interfaces)
- [Architecture](#architecture)
- [EPICS PV Access](#epics-pv-access)
- [GUI pages](#gui-pages)
- [Trip analysis and the AI assistant](#trip-analysis-and-the-ai-assistant)
- [Operations](#operations)
- [Configuration](#configuration)
- [Development](#development)

## Quickstart

On a fresh host with Docker and the NVIDIA container toolkit (and optionally
Ollama):

```bash
git clone https://github.com/bigsamich/liinac-virtual-accelerator.git
cd liinac-virtual-accelerator
./scripts/bootstrap_new_host.sh   # venv, seed ~/.pip2va, build, start, wait for MACHINE READY
make gui                          # native control room (optional)
```

The bootstrap script creates `.venv` with `.[gui,dev]`, copies the seeded
study results, knowledge base and golden snapshot from `data/seed/` into
`~/.pip2va/` (it creates that directory itself, so Docker does not make it
root-owned), runs `docker compose build` and `make reset`, and, if Ollama
answers on `:11434`, pulls `qwen3.6` and `qwen3-embedding:8b`, bakes the
`pip2va-expert` model and builds the code index.

By hand:

```bash
mkdir -p ~/.pip2va/studies ~/.pip2va/snapshots   # before the first compose up
docker compose up -d --build                     # 11 containers (make up)
python3 -m venv .venv && .venv/bin/pip install -e ".[gui,dev]"
make gui
```

Give the MPS ~15 s after startup to capture its BLM baseline ("armed" in the
MPS event log), then you have beam. `make status` checks the whole stack.

Building `epics-ws` compiles the Flutter web app in the image (a ~2 GB
Flutter SDK pull). To skip it: `WEBAPP_MODE=none docker compose build epics-ws`.

## Interfaces

| Interface | Where | Notes |
|---|---|---|
| Native GUI | `make gui` on the host | PyQt6, GPU-accelerated 3D, talks to redis on `localhost:6379` |
| Browser GUI | `http://<host>:6080/` | the same GUI on Xvfb, streamed by noVNC; scales to the window |
| Phone page | `http://<host>:6081` | Flask: permit, big numbers, trends, studies, ask |
| Web console | `http://<host>:8085/` | Flutter app + WebSocket PV gateway at `/ws` |
| EPICS PVA | host network, TCP 5075 / UDP 5076 | `epics-gateway`, all PVs under a prefix (default `SPARK`) |

None of these require a login. Keep them on the lab network.

## Architecture

Services talk through Redis: pub/sub for the 20 Hz tick and events, capped
streams (msgpack, 100 entries = 5 s) for telemetry, hashes for settings and
readbacks, all keyed by pulse ID. Key names live in `pip2va/common/keys.py`.

| Service | Role |
|---|---|
| `redis` | `redis:7-alpine`, published on host port 6379 |
| `timing` | 20 Hz master clock, pulse IDs, utilities model (cryo/LCW); honours pause/step (`state:sim.run`, `state:sim.step`) |
| `beam-physics` | **GPU.** Envelope pass every pulse (6D sigma transport, cavity phase slip, 3D-ellipsoid space charge, H⁻ stripping and aperture losses) and a free-running CuPy macroparticle tracker (`PIP2VA_MACRO_PARTICLES=400000`) for profiles, phase space, emittance and a particle-true loss map; Booster injection model |
| `rf-sim` | Physical SRF model per pulse: PI LLRF with loop delay, beam loading + feedforward, microphonics, Lorentz-force detuning with piezo loop, quenches, stochastic trips |
| `magnet-sim` | Supplies: slew, ripple, thermal drift, trips |
| `diag-sim` | Turns ground truth into noisy BPM/BLM/BCM/toroid/wire/laserwire measurements, 1000-sample intra-pulse waveforms and the trip postmortem buffer. The GUI never sees ground truth |
| `mps` | Beam permit: BLM baseline capture while delivering beam, per-monitor thresholds, latched trips, gated reset; vacuum interlock |
| `autotune` | RESCUE (restore every setpoint to design, reset tripped devices, re-arm the permit), SVD orbit correction, the study executor |
| `epics-gateway` | p4p PV Access server built from the services' self-registered streams and settings (not an IOC), plus the AI RPC PVs. Host networking |
| `epics-ws` | PVA client → JSON WebSocket on `:8085/ws`, serves the Flutter app. Host networking |
| `web-gui` | The PyQt6 GUI on Xvfb → x11vnc → noVNC (`:6080`) and the phone page (`:6081`) |

Setting flow: a client writes a `settings:*` hash → publishes
`settings.changed` → the owning sim slews its readback → `beam-physics`
transports the next pulse from *readbacks*. Trip a cavity and the beam
arrives late everywhere downstream, gaps slip off-crest, the energy profile
collapses, losses spike and the MPS pulls the permit. Every write from any
client is audited in `stream:settings.log`.

## EPICS PV Access

`epics-gateway` builds its PV list **once at startup** from the registry the
services write (`meta:stream:*`, `meta:settings:*`), then refreshes at
`PIP2VA_EPICS_HZ` (10 Hz). Every name is prefixed by `PIP2VA_PV_PREFIX`
(default `SPARK`) so two VAs, or a VA and a real machine, never collide.

| PV | Kind |
|---|---|
| `<P>:PIP2:BEAM:W`, `:T`, `:IOUT`, `:PULSE`, `:LAG` | beam energy, transmission, current, pulse ID, lag |
| `<P>:PIP2:INJ:SCORE`, `:PROTONS`, `:FOILHITS`, `:EPS`, `:DQSC`, `:EPSINJ`, `:CAPTURE` | Booster injection figures |
| `<P>:PIP2:MPS:PERMIT` | permit (1 = beam allowed) |
| `<P>:PIP2:MPS:RESET` | write 1: re-arm the permit |
| `<P>:PIP2:AUTOTUNE:RESCUE` | write 1: restore design, reset trips, re-arm (the GUI's RESCUE) |
| `<P>:PIP2:AUTOTUNE:ENABLE` | 1/0: continuous SVD orbit trim |
| `<P>:PIP2:<STREAM>:<FIELD>` | whole arrays, e.g. `PIP2:BPM:X`, `PIP2:BLM:WPM` |
| `<P>:<Complex>:<System>_<Group>_<Dev><ID>:<Signal>` | per-device readbacks, ED0011740 names, e.g. `SPARK:LSCL:HWR-1_INST_CAV1101:XPOS` |
| same with an `s` signal prefix | writable, limit-clamped settings, e.g. `SPARK:LSCL:HWR-1_LLRF_CAV1101:sPHS` |
| `..._SP` / `..._RB` | settings and readbacks of devices with no official name |

Setting PVs read 0 until something writes them; the live setting is in the
Redis hash.

Three RPC PVs answer from the local model (each introspects as an NTURI
template with a `query` string; an answer can take tens of seconds, so give
the client a long timeout, e.g. `pvcall -w 180`):

```bash
pvcall SPARK:AI:ASK query='what is the beam status?'        # VA assistant, live machine context
pvcall SPARK:AI:EXPLAIN query='<parameter page lines>'      # explains Param Page lines, no VA state
pvcall SPARK:AI:ANALYZE query='<plot figures>'              # shift-log summary of a Plot window
```

For EXPLAIN and ANALYZE, append `\n\nQUESTION: ...` to the query to ask
something specific. `help` or `?` returns usage. Answers start with the
engine that wrote them: `[llm:<model>]`, or `[rules]` / `[offline]` when
the model did not answer.

Discovery uses multicast only, no broadcast: search group `239.128.1.6`,
beacons to `239.128.1.7` (the `x-epics-env` anchor in `docker-compose.yaml`).
Set the host's interface **name** (not its IP) in `.env`:

```bash
EPICS_HOST_INTERFACE=enP7s7      # ip -o addr show | grep <host-ip>
PIP2VA_PV_PREFIX=SPARK           # must differ per VA on the same network
```

Clients can also use unicast, e.g. `EPICS_PVA_ADDR_LIST=<host>`.

## GUI pages

| Group | Pages |
|---|---|
| Overview | Dashboard (synoptic, toroids, live orbit/loss, 3D machine; click a section for its view) |
| Instrumentation | Orbit, Losses (per-BLM bars + waterfall), Profiles (wire/laserwire, phase space, emittance, 3D beam cloud, Allison), Scope (intra-pulse waveforms, postmortem), Bunch Monitor, Strip Tool, Booster Injection (score, capture, ΔQ_sc, foil hits, painting knobs) |
| RF & Magnets | RF, Magnets, Source & LEBT |
| Operations | Studies, Training, Snapshots, MPS (trip log, root cause, fault injector) |
| Machine | Physics, Utilities (cryo, LCW, vacuum) |

An always-visible banner carries the permit with **RESET PERMIT**,
**RESCUE** and the **Auto-tune orbit** toggle. A playback bar pauses,
single-steps and rewinds the last 5 s across every page. Every page has an
ask panel with a one-click **Status** report. User guides:
`docs/guides/00-overview.md`.

## Trip analysis and the AI assistant

Every MPS trip gets an instant rule-based diagnosis on the MPS page (loss
location, tripped devices upstream, injected faults, recent setpoint changes
from the audit trail). "Deep analysis" and the ask panels send the evidence
to a local Ollama model and fall back to the rule-based text when it is
unreachable.

- **Model.** `PIP2VA_LLM_MODEL` if set; otherwise the first present of
  `pip2va-expert-ft:latest` (only with an `EXAM_PASS` marker),
  `pip2va-expert:latest`, else `qwen3.6:latest`. The choice is made once,
  when the process starts.
- **Knowledge base** `~/.pip2va/studies/knowledge.jsonl`: every study
  result appends a finding; it is searched semantically with
  `qwen3-embedding:8b`, by keyword without it.
- **Code-RAG** `~/.pip2va/studies/code_index.npz`: an AST-chunked index of
  this source so the assistant can cite code. Build with `make code-index`.
- **Baked expert**: `make bake` (`scripts/distill/bake_expert.py`) writes
  facts and KB insights into a `pip2va-expert` Ollama model. The LoRA
  distillation pipeline is in `scripts/distill/`.

`web-gui` and `epics-gateway` mount `~/.pip2va/studies` for the KB and the
index.

## Operations

```bash
make status                      # scripts/health_check.sh: services, beam, streams, PVA, Ollama, code index
make smoke                       # heartbeats, 20 Hz streams, orbit response
.venv/bin/python scripts/e2e_check.py   # + cavity trip -> MPS trip -> recovery
make logs
make reset                       # docker compose down + up, waits for MACHINE READY
```

`make reset` wipes all machine state. To restore beam without that, write
`PIP2:AUTOTUNE:RESCUE` = 1 (or press RESCUE).

After a host reboot:

- The EPICS gateway can show Up while serving nothing (multicast join failed
  because it started before the network, or it built its PV list before all
  simulators registered). Restart it:
  `docker compose restart epics-gateway epics-ws`.
- A stale X lock in `web-gui` stops VNC (noVNC loads, never connects).
  Recreate it: `docker compose up -d --no-build --no-deps --force-recreate web-gui`,
  or give it a tmpfs `/tmp` in a `docker-compose.override.yaml`.

## Configuration

| Variable | Default | Used by |
|---|---|---|
| `PIP2VA_REDIS_URL` | `redis://localhost:6379/0` (compose sets `redis://redis:6379/0`) | all |
| `PIP2VA_PV_PREFIX` | `SPARK` | epics-gateway |
| `PIP2VA_EPICS_HZ` | `10` | epics-gateway |
| `EPICS_HOST_INTERFACE` | `enP7s7` | epics-gateway, epics-ws (compose) |
| `WEBAPP_MODE` | `full` | epics-ws build arg (`none` skips Flutter) |
| `PIP2VA_OLLAMA_URL` | `http://localhost:11434` (compose: `host.docker.internal` for web-gui) | assistant |
| `PIP2VA_LLM_MODEL` | auto (see above) | assistant |
| `PIP2VA_MACRO_PARTICLES` | `100000` (compose: `400000`) | beam-physics |
| `PIP2VA_BACKEND` | `auto` (`numpy`, `cupy`) | physics |
| `PIP2VA_ERRORS` | on (`0` = perfect machine, used by tests) | lattice errors |
| `PIP2VA_WS_PORT` | `8085` | epics-ws |

Per-host settings go in `.env` (gitignored) and `docker-compose.override.yaml`.

## Development

```bash
make test                         # pytest: ~96 tests, physics vs analytic results, services on fakeredis, GUI offscreen
.venv/bin/python scripts/bench_envelope.py
```

The lattice YAML is the source of truth. `scripts/gen_lattice.py` built it
and `scripts/match_lattice.py` matched it, but since 2026-07-06 the YAML has
been edited directly (BTL arcs, BINJ/BAL, vacuum, dual sources, BLM
placement) and the generator has not been updated, so **`make lattice` would
discard those changes**. Patch the YAML instead.

Docs: user guides in `docs/guides/`, design spec in
`docs/superpowers/specs/`, implementation plan in `docs/superpowers/plans/`,
machine physics references in `docs/research/`, study reports in
`docs/reports/`.
