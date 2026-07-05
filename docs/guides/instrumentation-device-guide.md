# PIP-II Virtual Accelerator — Instrumentation & Device Guide

*How every device works: the real physics, how this simulator models it,
and what our own beam-study program has measured about it.*

Machine at a glance: H⁻ ions, 30 keV source → RFQ (2.1 MeV, 162.5 MHz) →
MEBT with bunch-by-bunch chopper → SRF linac: HWR (10 MeV) → SSR1 (35) →
SSR2 (185, 325 MHz) → LB650 (516) → HB650 (800 MeV, 650 MHz) → Beam
Transfer Line (BTL) with 8 dipoles to the dump/Booster. 20 Hz × 0.55 ms
pulses; 5 mA pre-chop, ~2 mA delivered; bunches every 6.15 ns.

---

## Part 1 — Beam instrumentation (what you observe)

### 1.1 Beam Position Monitors (BPM) — 74 stations
**What it is.** Four button electrodes around the pipe. A passing bunch
images charge on each button; the top/bottom and left/right asymmetries
give the beam's transverse position; the sum gives intensity; the phase of
the 162.5 MHz signal against the RF reference gives arrival time.

**Physics.** For small displacements, position ≈ k·(A−B)/(A+B) per plane.
The phase measurement enables **time-of-flight (TOF) energy**: between two
BPMs a distance L apart, ΔΦ = 2πf·L/(βc), so measuring Δφ between BPM
pairs yields β and hence kinetic energy. Error propagation:
dW/W = γ(γ+1)·δφ·βc/(2πfL) — phase noise hurts most at high energy.

**In the simulator.** Each BPM has a position noise floor (~10 µm,
growing as charge drops), an **electrical offset** (~0.1 mm rms — the
electrical center is not the magnetic center), a scale error (~2%), and
an aperture clamp (a BPM cannot report beyond its bore). Phase noise plus
an **LCW-temperature systematic** (§3.2) feed the TOF energy readout.

**Measured on this machine.** The offsets floor SVD orbit correction at
~250 µm of true orbit — which is why loss-based steering beat BPM-based
steering 21 → 4.5 W/m. Beam-based alignment (BBA, quad-shunt method) is
the cure: it measures each BPM's offset against its quad's magnetic
center. TOF energy stability measured 800.01 ± 0.23 MeV (0.03%).

**Where.** Orbit page (x/y along the machine, device-name axis), section
views (3D markers ride the live orbit), dashboard synoptic.

### 1.2 Beam Loss Monitors (BLM) — 46 stations
**What it is.** Ionization chambers along the tunnel that integrate
radiation from beam particles striking the aperture. Read out in W/m of
deposited beam power.

**Physics.** Loss power = lost fraction × beam power at that energy: the
same fractional loss is 400× more damaging at 800 MeV than at 2 MeV.
The **1 W/m rule**: high-energy hadron machines keep losses near 1 W/m so
components stay hands-on maintainable (activation). Hence our
energy-dependent thresholds: activation limit ∝ 1 W/m scaled by
clip(200/W, 1, 100) — permissive at the front end, strict in the BTL.
Loss vs orbit error is strongly nonlinear (measured: excess ∝ kick^3.3 —
Gaussian tail scraping).

**In the simulator.** True losses from the envelope engine (aperture
scraping + intra-beam stripping + residual-gas stripping — both real H⁻
loss mechanisms) plus **field-emission background** from pushed cavities
(x-rays land on the nearest BLM), dark-current noise, and per-pulse
counting noise. The MPS (§4.1) learns baselines from these.

**Measured.** BTL:BLM1 (entrance collimation) is the machine's tightest
constraint: quiescent losses sit near its strict 1 W/m-class limit and
respond to *linac energy spread* — front-end phase errors trip it while
transmission still reads 99.3%. Quiescent losses also drift +0.1 W/m/min
on a mis-steered machine (baselines stale hourly).

**Where.** Losses page (vertical device axis with threshold staircase),
dashboard (vertical bars + red 3D spikes), postmortem waveforms.

### 1.3 Beam Current Monitors (BCM / toroid) — 9 stations
**What it is.** A toroidal current transformer around the pipe: the beam
is the one-turn primary. Bandwidth covers the macro-pulse (droop limits
DC response), giving pulse current and, between pairs, transmission.

**In the simulator.** Per-toroid noise (~0.2%) and floor (~5 µA); full
intra-pulse waveforms (1000 samples across 0.55 ms) with rise/fall and
chopper structure; the dashboard's boundary-transmission strip divides
adjacent toroids. The chopper boundary legitimately removes ~60% of beam.

**Where.** Dashboard vertical BCM histogram (LEBT top → BTL bottom),
boundary-T strip, waveform viewer, 3D beamline glow (current-scaled).

### 1.4 Resistive Wall Current Monitors (RWCM) — MEBT + BTL
**What it is.** A ceramic gap in the beam pipe bridged by resistors: the
beam's image current flows through them, giving a signal flat from
~10 kHz to ~4 GHz — fast enough to resolve **individual 6.15 ns bunches**
(PIP2IT used exactly two of these).

**Physics.** Peak current of a Gaussian bunch = q/(√2π·σ_t): a 30.8 pC
bunch at σ=80 ps peaks at ~150 mA. Its mission is **chopper extinction**:
proving removed bunches are gone to the 10⁻⁴ level, which only a
bunch-resolved monitor can do.

**In the simulator.** Publishes 160-bucket windows per pulse: per-bunch
charge follows the *actual programmed pattern* from the BPG (§2.4),
chopped buckets carry ~1.2×10⁻⁴ leakage, bunch length σ_t comes from the
tracked σ_z at each monitor (≈300 ps MEBT, ≈80 ps BTL). The Bunch
Monitor page reconstructs the scope trace (Gaussians on the bucket grid)
and overlays the programmed pattern; **pattern verification** compares
measured vs programmed bunch-by-bunch and raises an event on mismatch
(catches a stuck chopper pulser).

### 1.5 Wire scanners — 14 stations (warm sections)
**What it is.** A thin wire stepped across the beam; secondary emission /
scattering signal vs position gives the transverse profile. Invasive —
and thermally forbidden at full power in the SC linac.

**In the simulator.** Profiles come from the 400k-macroparticle GPU
tracker's histograms, so they show the **real distribution including
tails** (halo from mismatch is visible here first). Scan speed and
points/pulses-per-point are configurable; scans step one position per
`ppp` pulses like the real actuator.

### 1.6 Laserwires — 12 stations (SC linac)
**What it is.** PIP-II's non-invasive profiler: a laser focused to
<100 µm rms crosses the H⁻ beam; photons detach the loosely-bound outer
electron (photodetachment); the freed electrons are bent up into a
Faraday cup. Counting rate vs laser position maps the profile with the
beam untouched — usable at full power where a wire would melt.

**Physics.** H⁻ binding energy is only 0.75 eV; 1064/355 nm photons
detach it with large cross-section. Measured width = beam ⊗ laser focus
in quadrature; counting is Poisson.

**In the simulator.** Profiles from the envelope truth convolved with
the 0.1 mm laser focus plus Poisson statistics — clean Gaussians, no
tails: deliberately a *different systematic* from the wire scanners.
**Cycle scans** step every wire and every laserwire one at a time in
parallel, ending in a measured σ(s) plot vs the model.

### 1.7 3D beam cloud & emittance
The GPU tracker dumps a 30k-particle (x,y,z) cloud at a selected
station (Profiles page, and rendered on the dashboard synoptic at true
mm scale, cyan core / orange >3σ halo). Emittance vs s comes from the
same tracker (measured: ε_x grows 0.250→0.279 µm from 4→5.5 mA — space
charge; ε_y flat).

---

## Part 2 — Actuators (what you control)

### 2.1 Ion source & LEBT
30 keV H⁻ source (0–15 mA setpoint) into three LEBT solenoids. Source
current sets the space-charge scale for everything downstream: this
machine is **matched at exactly 5.0 mA** — losses form a U-curve (175 W/m
at 4.0, 27 at 5.0, 40 at 5.5): running *below* nominal is worse than
above. Intensity changes in either direction require MPS re-baselining;
the validated recipe for raising current couples source + RFQ amplitude
(+1.5% at 6 mA → 7× loss reduction) + rebaseline plateaus + orbit trim.

### 2.2 RFQ
4-vane, 162.5 MHz, 30 keV → 2.1 MeV (below the neutron-production
threshold — a maintenance decision). Amplitude is the front-end
transmission knob: measured curve falls off a cliff below 0.97×design
(T 0.995 → 0.60) with the as-built optimum at 1.01. Phase errors at the
RFQ/bunchers are the machine's **knife edge** (§2.3).

### 2.3 MEBT bunchers & the longitudinal knife edge
Three 162.5 MHz buncher cavities keep the beam bunched between RFQ and
HWR. Physics: at 2.1 MeV, timing errors amplify — a phase error changes
energy, energy changes velocity, velocity converts to a *growing* phase
slip in every downstream cavity. The bunch centroid is re-centered by
synchrotron focusing only within ±30° of the bucket; beyond that the
cascade is fatal. **Measured: buncher phase tolerance is ±1–3°** (vs
±5° everywhere else), and errors this small trip the *BTL* through
energy spread before transmission shows anything.

### 2.4 Chopper & Bunch Pattern Generator (BPG)
The MEBT chopper kicks individual bunches to a dump, programmable
per-bucket. Modes: `duty` (keep-fraction), `booster` (micro-pattern +
extraction-kicker notch per Booster turn — injection paints ~285 turns
per 0.55 ms pulse via a stripping foil), `custom` (bitmask). The
pattern's mean transmission drives beam current and RF loading
everywhere (verified: notch 10→70 buckets cuts delivered current
1.51→1.14 mA, exactly avg-duty). Faults: `stuck_bucket` (a pulser that
always passes) — visible on the RWCM and flagged by verification.
Reprogramming the pattern **is** an intensity change: rebaseline after.

### 2.5 SRF cavities — 123 across five families
**What they are.** Superconducting resonators: HWR (half-wave, 162.5
MHz), SSR1/SSR2 (single-spoke, 325 MHz), LB650/HB650 (5-cell elliptical,
650 MHz), geometry matched to the rising β. Each has an SSA amplifier
(7–70 kW class), an LLRF loop, and a piezo tuner.

**The physics stack modeled per cavity, per pulse:**
- **Complex envelope ODE**: dV/dt = (ω/2Q_L)(V_for·2 − V) + jΔω·V − beam
  loading; solved with exact exponential updates, 220 steps/window.
- **Beam loading**: the beam is a current source |I_b| = 2·I_DC at the
  bunch phase; at nominal it rivals the generator (V_b/V up to 2.4 on
  de-rated capture cavities). The LLRF gated **feedforward** injects the
  compensating drive exactly during the beam gate — measured: fading FF
  makes the residual dip grow linearly, reaching (V_b/V)/(1+G_p) at
  FF=0 (0.132% on HB650, matching theory to 9%) — which is why FF is
  mandatory in pulsed mode.
- **Feedback**: proportional+integral around the setpoint, gains scaled
  by cavity bandwidth; regulation achieved: 0.0004% / 0.011° class
  (spec: 0.065%/0.065°).
- **Microphonics**: Ornstein–Uhlenbeck detuning wander + discrete
  vibration lines (~3 Hz rms achieved; matches LCLS-II statistics).
- **Lorentz force detuning**: radiation pressure detunes ∝ E²acc
  (kL Hz/(MV/m)²), rung analytically each pulse; compensated ~90% by
  the piezo feedforward.
- **Pressure sensitivity df/dp**: He bath pressure shifts frequency a
  few Hz/mbar (SSR2 ≈ −3.4 measured on real cavities); the **piezo
  loop absorbs static shifts entirely** — measured: ±3 mbar plant
  excursions are invisible at steady state.
- **Quench**: Q₀ collapse when a cavity exceeds its quench field;
  recovery requires clearing the fault and re-ramping. Trip statistics
  follow the CEBAF trip law near the field limit.
- **Field emission**: above a random onset gradient, x-ray background
  grows exponentially and lands on nearby BLMs — pushing gradients has
  a radiation cost before it has a quench cost.

**Failure recovery (validated on this machine).** A dead cavity is
recoverable: neighbors at +15% amplitude restore full energy (799.8 MeV,
T=99.45%) — the two-knob compensation recipe. Coherent section phase
shifts (LLRF reference drift) are benign at ±6°; the *only* fragile
phases are the front end's.

### 2.6 Solenoids (40) and quadrupoles (63)
Solenoids focus both planes at low energy (LEBT/HWR/SSR1/SSR2);
quad doublets/triplets take over in the 650 sections and warm lines.
Power supplies drift thermally (part of the measured +0.1 W/m/min
quiescent creep). Measured tolerances: solenoids ±2% (HWR) to ±3%
(SSR1/SSR2) — tighter *at* the space-charge match point; quads ±3%
everywhere except the **MEBT triplet, the machine's sharpest optics
knob** (coherent ±4% scaling → 252 W/m). A drifting solenoid can be
compensated by counter-trimming a neighbor (beat cancellation).

### 2.7 Correctors (71 × 2 planes)
Small dipole trims. Single-corrector danger is *state-dependent* (loss ∝
kick^3.3): harmless at ±0.8 A on a well-steered machine, near-critical
on a mis-steered one. The symmetric 1:−2:1 three-corrector bump closes
(orbit stays local). The SVD **auto-tune** loop (2 s cadence, ±0.3 A
step clamp, 250 µm deadband, weak-column excision) recovers a 2.5 A
perturbation in ~20 s but deliberately ignores sub-deadband errors and
optimizes BPM readings, not losses — loss-based pair steering remains
the optimizer on top.

### 2.8 BTL dipoles & debuncher
Eight fixed-field bends steer 800 MeV beam to the dump; dispersion in
the bends converts momentum error to position (measured: 14–22 mm per
unit ΔW/W at the arc BPMs vs 1.8 in straights — the energy-jitter
signature). The entrance collimation is the machine's activation
bottleneck; the debuncher (300 kW SSA) reduces momentum spread but sits
*downstream* of it — it cannot protect the entrance.

---

## Part 3 — Utilities (the plant that leaks into everything)

### 3.1 Cryogenics
One plant, three levels: 40 K shields, 4.5 K intercepts, 2 K superfluid
(saturated at ~31 mbar) for the cavities. 15 cryomodules modeled with
individual bath pressures (slow wander + 8-min plant breathing).
Coupling: df/dp per family → cavity detuning; the piezo loops null
static offsets of either sign up to at least ±3 mbar (measured both
directions). What would bite: fast excursions and tuner-range
exhaustion — not slow plant wander.

### 3.2 Low-conductivity water (LCW)
Regulated 35 ± 0.6 °C (95 °F) at service buildings. It cools the *racks
and amplifiers*, so it couples into **electronics, not beam**: BPM
phase drift (~0.03°/°C calibrated residual) → the TOF energy *readout*
shifts ~0.06 MeV/°C while the real beam is untouched; SSA forward-power
calibration drifts ~0.4%/°C. Operational lesson: an "energy drift" with
a 20-minute period is the water, not the beam — check Utilities before
touching RF.

---

## Part 4 — Protection & automation

### 4.1 Machine Protection System (MPS)
Compares each BLM's 10-pulse rolling mean against thresholds =
max(energy-scaled activation base, learned baseline mean+8σ, 3×mean),
with commissioning masks while learning. Trips drop the beam permit in
one pulse. Baselines go stale as the machine drifts (~hourly);
`relearn` re-captures them — required after any intensity change,
steering campaign, or pattern reprogram. Quiescent-EMA auto-maintenance
gently tracks slow drift (capped at 5× the activation base so real
growth still trips). Errant-beam events (source glitches, ~12/hr at
full duty) are transient and distinguished from real trips by the
study executor.

### 4.2 Auto-tune, restore, and the study executor
Auto-tune = SVD orbit stabilizer (§2.7). RESCUE = cold-restart restore:
permit off → design+golden setpoints → converge readbacks → relearn →
verify transmission. The study executor runs sweeps with: settle after
arming, errant-event retry, marginal-trip auto-rebaseline, reset→relearn
escalation, per-plan pre-settings, and per-step capture (losses, T, TOF
energy, orbit, emittance, RF detuning, beam-loading waveform metrics).
155+ consecutive unattended studies without a trip.

### 4.3 The knowledge loop
Every study result feeds `~/.pip2va/studies/knowledge.jsonl`; distilled
insights are baked into the `pip2va-expert` LLM (and the fine-tuned
`pip2va-expert-ft` student); live state rides in via RAG. Ask-the-machine
(every GUI page + phone) answers from measured ground truth.

---

## Quick reference — where to find things

| Page | What |
|---|---|
| Dashboard | big values, orbit/BLM/BCM plots, boundary T, 3D synoptic |
| Orbit | x/y orbit, TOF energy trace, corrector budget, BBA |
| Losses | BLM bars vs thresholds, loss history |
| Profiles | wire + laserwire scans, cycle scans, σ(s), 3D cloud |
| Bunch Monitor | RWCM scope/bars, pattern generator, extinction |
| Waveforms | intra-pulse toroid/BLM/RF waveforms, postmortem |
| RF | per-cavity table, phase-scan tune-up, detuning |
| Magnets | solenoid/quad/corrector table and trims |
| Utilities | cryo pressures, LCW, fault injection |
| MPS | thresholds, events, trip analysis (LLM), fault injector |
| Studies | AI planner, presets, queue, history, KB |
| Training | 15 tiered scenarios with AI debrief |
| Phone (:6081) | status, trends, studies queue, ask-the-machine |
