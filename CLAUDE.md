# CLAUDE.md — liinac-virtual-accelerator (pip2va)

The PIP-II virtual accelerator ("the VA"): a 20 Hz simulated 800 MeV H⁻ linac
plus transfer line, as 11 Docker services on one Redis, with a PyQt6 GUI,
an EPICS PV Access server, and RPC PVs answered by a local Ollama model.
`README.md` describes the system for people; this file is what costs time.
GitHub `bigsamich/liinac-virtual-accelerator` is the user's own repo:
feature branch, PR to `main`, the user merges.

## Where it runs

| | spark.FNAL.GOV | iskra.FNAL.GOV |
|---|---|---|
| Checkout | `~/Workspace/liinac/liinac-virtual-accelerator` | same path (copied from spark) |
| Compose project | `pip2va` (11 containers) | `pip2va` |
| PV prefix | `SPARK` | `ISKRA` |
| GUI / phone / web console | :6080 / :6081 / :8085 | :6080 / :6081 / :8085 |
| From the workstation | `spark-llm` tunnel: 6080, 6081, 8085 | `iskra-llm` tunnel: 26080, 26081, 28085 |

- **What is deployed is not this repo's HEAD.** Each box has a
  `docker-compose.override.yaml` (Ollama address, `PIP2VA_LLM_MODEL=qwen3.8:27b`,
  tmpfs `/tmp` for web-gui, iskra's prefix) and changed files bind-mounted
  over the image copies. spark's VA redis is on host port **6380** by a local
  change that is not in this repo. The record of what runs where is
  `~/workspace/instrumentation/spark-ai/docs/projects/pip2va.md`; read it, and
  the host's own `~/CLAUDE.md`, before touching either box.
- Both boxes are **offline**. `docker compose build` there cannot fetch pip
  packages, base images or the Flutter SDK. So far, code changes have been
  deployed by bind-mounting the edited file via the override and recreating
  the one service (`--no-build`). A real rebuild needs the spark-fetch route.
- On this workstation, the `pip2va-check` skill covers health after reboots,
  and `host-change` covers recording any change made on spark or iskra.
- The user calls `epics-gateway` "the IOC".

## Layout

- `pip2va/services/<name>/main.py` — one module per compose service:
  `timing`, `beam_physics`, `rf_sim` (+ `cavity_model.py`), `magnet_sim`,
  `diag_sim` (+ `waveforms.py`), `mps`, `autotune`, `epics_gateway`,
  `epics_ws`. `pip2va/mobile.py` is the phone page (Flask, :6081).
- `pip2va/common/` — `keys.py` (every Redis key/channel; never build keys
  with raw f-strings elsewhere), `schema.py` (services self-register streams
  and settings; the gateway reads this), `naming.py` (ED0011740 names),
  `codec.py` (msgpack), `audit.py`, `config.py` (`PIP2VA_*` settings).
- `pip2va/physics/` — envelope, macroparticle tracker, losses, injection.
- `pip2va/analysis/` — `llm.py` (Ollama, model pick, trip analysis),
  `assistant.py` (ASK / EXPLAIN / ANALYZE prompts), `knowledge.py` (KB),
  `codebase.py` (code-RAG index), studies, scenarios, root cause.
- `pip2va/gui/` — PyQt6 app, `pages/` one file per page.
- `pip2va/lattice/pip2_lattice.yaml` — the machine; `errors.yaml` misalignments.
- `webapp/` — Flutter web console, built inside `docker/epics-ws.Dockerfile`.
- `docker/` — one Dockerfile per image; `web-gui-entrypoint.sh` (Xvfb, x11vnc,
  noVNC patching, phone page, GUI restart loop).
- `scripts/` — `bootstrap_new_host.sh`, `health_check.sh` (`make status`),
  `smoke_compose.py`, `e2e_check.py`, lattice tools, `distill/` (bake,
  dataset, LoRA training).
- `data/seed/` — study results, KB and golden snapshot copied to `~/.pip2va`.

## Commands that work

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[gui,dev]"
make test          # 95 passed, 1 skipped in ~50 s without PyQt6 (2026-11-24)
make status        # full health check of a running stack (uses the containers)
docker compose up -d --no-build --no-deps --force-recreate <service>
docker compose logs -f --tail=50 epics-gateway
```

Tests set `PIP2VA_ERRORS=0` (perfect machine) and use fakeredis; no Docker or
GPU is needed. PV checks use PV Access tools (`pvxget`, `pvcall`), never `caget`.

## EPICS gateway gotchas

- **It builds its PV list once, at startup**, from the registry the
  simulators write. `main()` waits `while len(gw.plan) < 10`, but the plan
  always holds 16 fixed PVs, so it never waits: started together with the
  simulators it serves a partial list (seen: 1,077 instead of 2,855). The log
  line `PVA registry: N PVs` shows the count. Restart `epics-gateway` once
  the sims are up.
- **After a reboot it can show Up and serve nothing**: it started before the
  network, the multicast join (239.128.1.6) failed, and nothing logs it.
  Restart `epics-gateway` and `epics-ws`.
- Prefixes must differ per VA: spark and iskra share a subnet and multicast
  group. `EPICS_HOST_INTERFACE` is an interface **name**, not an IP.
- Setting PVs (`…:s<SIG>`, `…_SP`) read 0 until written; the live value is in
  the Redis `settings:*` hash (`docker exec pip2va-redis-1 redis-cli`).
- The Flutter web app (`webapp/lib/main.dart`) subscribes to unprefixed names
  (`PIP2:BEAM:W`), but the gateway serves `SPARK:PIP2:BEAM:W` since commit
  42019af, so the app's live values probably stay empty. Its RPC calls go
  through Redis and are unaffected. Not confirmed live.

## AI RPCs

- `<P>:AI:ASK` (VA assistant with live machine context), `<P>:AI:EXPLAIN`
  (Param Page lines, no VA state; used by param-page-tui's `E`),
  `<P>:AI:ANALYZE` (Plot figures as a shift-log note; used by plot-tui's
  Analyze). Prompts are in `pip2va/analysis/assistant.py`.
- EXPLAIN/ANALYZE rules the TUIs rely on: plain text, under 200 words, the
  oddest line first, say how to set a value but never what value to set,
  answer about the program from the HELP section sent with the query. Keep
  them when editing the prompts; `tests/test_explain.py` and
  `tests/test_analyze.py` cover the prompts and the request parsing.
- The model is picked **once, at import**: `PIP2VA_LLM_MODEL`, else
  `pip2va-expert*` if Ollama lists it, else `qwen3.6:latest`. If Ollama is
  down when the service starts, it stays on the fallback until restarted.
- `epics-gateway` runs on the host network and reaches Ollama at
  `localhost:11434` (compose sets no `PIP2VA_OLLAMA_URL` for it); `web-gui`
  uses `host.docker.internal`. On both boxes the override points web-gui at
  the `llm` network instead.
- The VA's own models (qwen3.6, pip2va-expert, qwen3-embedding) are not
  loaded on spark or iskra, by choice (same six Ollama tags on both boxes).
  KB lookup then falls back to keywords, and code-RAG adds nothing (it
  embeds each query with `qwen3-embedding:8b`).
  Don't pull models onto either box without asking.

## Other traps

- **Never run `make lattice`.** `gen_lattice.py` was last changed 2026-07-06;
  the YAML has been hand-edited many times since (BTL arcs, BINJ/BAL,
  vacuum, dual sources, BLM placement). Regenerating discards all of that.
  Patch the YAML.
- **`make reset` is `docker compose down` + `up`**: it wipes machine state. On
  spark or iskra, use `PIP2:AUTOTUNE:RESCUE` = 1 instead, and only when asked.
- `make reset`, `make smoke` and `scripts/e2e_check.py` talk to
  `localhost:6379`. On spark that is the general-purpose redis, not the VA's
  (which is on 6380 there). Check the port before running them on spark.
- The `redis` service publishes host port 6379; it collides with any redis
  already on the host.
- Create `~/.pip2va/studies` and `~/.pip2va/snapshots` before the first
  `compose up`, or Docker creates them root-owned and host writes fail.
- A stale `/tmp/.X1-lock` in web-gui after a reboot: noVNC loads but never
  connects while every container is Up. tmpfs `/tmp` (the hosts' overrides)
  prevents it; `--force-recreate web-gui` fixes it.
- At design settings the beam trips on `LB650:BLM2` (1.02-1.06 W/m against
  1.00). With Auto-tune ON it trips about 2 s after a RESCUE; with Auto-tune
  OFF the beam stays on. This is an open tuning issue (2026-11-14) that has
  not been worked on.
- Some `docs/guides/` pages and the Makefile's `gui-web` message name an old
  host. Use `spark.fnal.gov` / `iskra.fnal.gov` or `<host>`.

## Rules

- No Claude attribution in commits or PRs (machine rule).
- Stage files by name. Don't commit `.env`, `docker-compose.override.yaml`,
  `scripts/distill/` outputs or `~/.pip2va` contents.
- No writes to a deployed VA's settings unless the user asks. RESCUE is the
  agreed way to bring the beam back.
- After changing what runs on spark or iskra, update
  `spark-ai/docs/projects/pip2va.md` (status and history).
