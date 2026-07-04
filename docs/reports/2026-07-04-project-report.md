# PIP-II Virtual Accelerator — Project Report

**Date:** 2026-07-04 · **Repo:** `pip2va` on `main` · **Tests:** 81 green
**Platform:** NVIDIA DGX Spark (GB10, aarch64, CUDA 13), Docker Compose backend, native PyQt6 GUI

---

## 1. What was built

A research-grade virtual accelerator of the **Fermilab PIP-II 800 MeV H⁻
superconducting linac**, running at the machine's real 20 Hz pulse rate:

```
LEBT → RFQ → MEBT → HWR → SSR1 → SSR2 → LB650 → HB650 → BTL
30 keV  2.1 MeV      10.3    35     185    516     800 MeV
          162.5 MHz  |  325 MHz     |     650 MHz
```

- **711 lattice elements / 198 m**: 123 RF cavities, 103 powered magnets,
  74 BPMs, 46 BLMs, 9 toroids, 14 wire/laserwire scanners
- Machine parameters (cavity counts, V_eff, loaded-Q table, synchronous-phase
  law, loss physics, alignment budgets) traced to **two adversarially
  fact-checked research reports** (~50 primary sources total) in
  `docs/research/`
- `docker compose up` boots 8 containers (redis + timing, beam-physics [GPU],
  rf-sim, magnet-sim, diag-sim, mps, autotune); `make gui` opens the
  control room

## 2. Physics engines

| Engine | Cadence | Content |
|---|---|---|
| **Envelope** (NumPy, ~7 ms/pulse) | every pulse | 6×6 transport of centroid + 6D sigma matrix; phase-slip cavity physics (trip a cavity and everything downstream slips off-crest); 3D-ellipsoid space charge with longitudinal debunching; sector-bend dispersion in the BTL; Gaussian-tail scraping + verified H⁻ losses |
| **Macroparticle** (CuPy on GB10, 400k particles, ~3 s/pass) | free-running | nonlinear per-particle RF kicks, hard-aperture collimation, nonlinear Gaussian space-charge kicks, wire profiles, phase-space images, emittance evolution, particle-true loss maps, 3D beam clouds at scanner stations |
| **SRF cavity bank** (all 124 cavities, ~6 ms/tick) | every pulse, 220 steps across the 0.55 ms window | complex-envelope ODE (exact exponential update); PI LLRF with loop delay; gated beam loading (\|Ib\|=2·I_DC) + feedforward; SSA saturation with anti-windup; stochastic microphonics (OU He drift + wandering acoustic lines + bursts); Lorentz-force detuning with piezo loop; physical quenches (Q₀ collapse — the field dies *inside* the pulse window); CEBAF-law gradient-dependent stochastic trips |

**Fidelity anchors** (model vs published):
- LLRF regulation 0.0004 % amp / 0.011° phase rms (spec 0.065 %; PIP2IT measured 0.008–0.029 %)
- Detuning rms 2.7 Hz / peak 9 Hz (LCLS-II statistics; 20 Hz budget)
- HB650 forward power with beam ≈ 24–41 kW (published 24.3→40.7 kW)
- Design transmission 99.87 % at 5 mA with space charge; losses < 0.75 W/m
- δp/p at linac exit 4σ ≈ 3×10⁻⁴ (design class 2×10⁻⁴)
- H⁻ losses: Lebedev intrabeam stripping (σ_max = 4×10⁻¹⁹ m²), β⁻² residual-gas stripping

## 3. The "as-built" machine

The simulator boots an *imperfect* machine: seeded quad/solenoid
misalignments, BPM electrical offsets (~0.1 mm) and scale errors. The orbit
wanders ~1 mm rms with a visible hot BLM; the MPS captures its baseline on
the running machine (commissioning mode masks BLMs except catastrophic
loss) and builds a per-monitor threshold table. Steering it out is the
operator's (or autotune's) job — like a real cold start.

## 4. Operations layer

- **MPS**: latched beam permit, 10-pulse rolling means against learned
  per-BLM thresholds, gated reset, trip history
- **Autotune**: RESCUE (clears faults, resets trips, slews all 226 setpoints
  to design/golden, re-arms permit — dead machine to 800 MeV in seconds) and
  continuous SVD orbit trim against a model-measured response matrix
  (Tikhonov-regularized, noise-floor deadband, weak-corrector excision)
- **Snapshots**: SCORE-style save / compare / restore of the full machine
- **Audit trail**: every setpoint write logged with source (gui / autotune /
  fault-injection / restore)
- **Fault injection**: trips, detunes, drifts per device with TTLs — training
  scenarios
- **LLM root-cause analysis**: every trip triggers an instant rule-based
  diagnosis (loss location, tripped devices upstream, active injections,
  recent setpoint changes); "Deep analysis" sends the evidence pack to the
  local Ollama **qwen3.6** for a physics narrative with recovery steps
  (~6 s), falling back to rules if offline

## 5. Control-room GUI (PyQt6 + pyqtgraph, 12 pages + section views)

Dashboard (synoptic, click-through sections), Orbit (device-name axes,
reference diff, TOF energy trace, corrector steering budget), Losses (bars +
waterfall vs 0.1/1 W/m), Magnets, RF (per-cavity table + detuning detail),
Profiles & phase space (+ 30k-particle 3D GL beam cloud), Waveforms
(1000-sample intra-pulse traces: toroids, BPMs, BLMs, **RF cavities showing
real beam-loading transients**; trip postmortem buffer), Strip tool,
Snapshots, **Physics** (every model parameter live-tunable: space charge,
IBSt/gas scales, vacuum pressure, dispersion closure, source/chopper),
Source & LEBT, MPS (permit, trip log, analysis, fault injector). Global
banner: permit state + RESET + RESCUE + auto-tune toggle on every page.
Plot toolkit: crosshair readouts, legends on every plot, rigid auto-Y
(expands instantly, shrinks patiently, locks on manual zoom), device-name
axes (`MEBT:BPM01`) with s-metres toggle, full-span default zoom.

## 6. Incidents found & fixed by operating the machine

1. **Threshold collapse**: MPS re-learned its BLM baseline while the beam
   was off → thresholds fell to the floor → every reset re-tripped.
   *Fix: learn only while delivering; commissioning thresholds during capture.*
2. **Hidden debunching**: the macro beam had been longitudinally unconfined
   since v1 (δ spread 24 %!) — invisible until real dipole dispersion
   exposed it. *Fix: stability-capped longitudinal maps (stand-in for the
   adiabatic design ramp); bunch now design-scale.*
3. **Ponderomotive instability**: the SRF model developed a real detuning
   death-spiral (field sag → LFD → detuning → deeper sag). *Fix: the piezo
   feedback loop — the model needed it for the same reason real cavities do.*
4. **BTL:C12 corrector runaway** (today, diagnosed live with the LLM
   analyst): orbit trim chased BPM noise below the measurement floor,
   random-walking the least-constrained corrector to −8 A → aperture
   scraping at BTL:BLM6 → trip. *Fixes: noise-floor deadband (250 µm),
   weak-response-column excision with hard leak, per-step clamp, and RESCUE
   now restores correctors to the golden snapshot instead of zero
   (zeroing trims on a misaligned machine throws the orbit away).*

## 7. Current live state

W = 799.8 MeV, T = 99.87 %, permit ON, orbit 0.27 mm rms (at the BPM
systematic floor), worst BLM 1.3 W/m (MEBT chopper region, within its
threshold), C12 cleared, clean golden snapshot saved.

## 8. Roadmap candidates

Beam-based alignment as a trainable procedure · FN radiation folded into BLM
backgrounds · adiabatic-capture lattice generation (removes the ramp-cap
stand-in) · EPICS PV gateway (SNS-style: run real control-room tools against
the VA) · fused-kernel GPU tracker for per-pulse macroparticles.
