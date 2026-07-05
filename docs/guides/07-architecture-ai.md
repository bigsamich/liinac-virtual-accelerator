# 07 — Architecture & the AI stack

## Services (docker compose)
| Service | Role |
|---|---|
| redis | pub/sub (pulse.tick, settings, MPS), streams (msgpack), hashes (settings:/readback:/truth:/state:) |
| timing | 20 Hz master clock + utilities model (cryo/LCW) |
| beam-physics | envelope engine every pulse (NumPy, ~10 ms) + 400k-particle GPU tracker (CuPy) |
| rf-sim | physical SRF cavity bank: envelope ODE, LLRF PI+FF, microphonics, LFD+piezo, df/dp, quench, field emission |
| magnet-sim | supplies: slew, ripple, thermal drift, trips |
| diag-sim | instruments: BPM/BLM/BCM synthesis, waveforms, RWCM+pattern verify, wire/laserwire scans, postmortem |
| mps | thresholds, baselines, permit |
| autotune | SVD orbit trim, BBA, cold-restart restore, the study executor |
| web-gui | browser GUI (noVNC) + phone dashboard (Flask :6081) |

Native GUI (`make gui`) runs on the host against the same redis.

## Physics engines
- **Envelope**: 6×6 sigma-matrix transport through all 711 elements
  with 3D-ellipsoid space charge, adiabatic-capture longitudinal design,
  bucket-gated synchrotron re-centering, H⁻ loss physics (IBSt, gas
  stripping, aperture), as-built misalignments (errors.yaml).
- **Macro**: 400k particles on the GPU (~3 s/pass): distributions,
  tails, emittance, profile histograms, 3D clouds.
- Lattice generated (gen_lattice.py capture solver) then numerically
  matched (match_lattice.py) — patch the YAML, don't regenerate.

## The AI stack
- **Ollama endpoint**, model auto-preference: `pip2va-expert-ft`
  (LoRA fine-tuned Qwen3-8B student, trained on the machine's own
  study corpus + PIP-II facts) → `pip2va-expert` (36B teacher with
  distilled insights baked into its system prompt) → stock qwen3.6.
- **Knowledge base** (`~/.pip2va/studies/knowledge.jsonl`): every study
  result auto-appends a finding; insights are distilled after
  campaigns. Consumers: study planner (KB-informed spans), trip
  analyzer (prior findings as evidence), ask-the-machine, training
  debriefs.
- **RAG vs baked**: live state and fresh findings ride the prompt;
  stable knowledge lives in the model (system prompt or weights).
  Re-distillation: `scripts/distill/run_retrain.sh` (dataset from KB +
  results + facts pack → LoRA → GGUF → ollama).

## Operational lifelines
`make reset` = pristine machine in ~90 s. RESCUE = restore to golden.
MPS Relearn after intensity/steering/pattern changes. Everything a GUI
does goes through audited settings hashes — scripts and the phone use
the same contracts.
