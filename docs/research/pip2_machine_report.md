# PIP-II Superconducting Linac — Technical Reference for Virtual Accelerator Simulation

**Fact-check status:** compiled from ~25 primary sources (Fermilab RDR/CDR, JACoW proceedings, arXiv 2023–2025 papers, PIP2IT commissioning results), with contested values adversarially cross-checked. Values marked **(~)** are approximate or design-era; conflicts between the 2015–2017 design reports and the current (2023–2025) baseline are flagged explicitly. **Where two energy sets appear, the "nominal" set (…185/800 MeV) is the project spec; the "design-reach" set (…177/833 MeV) matches the actual lattice files — use the latter for lattice construction.**

**Key documents:**
- PIP-II Reference Design Report, FERMILAB-DESIGN-2015-01 — https://lss.fnal.gov/archive/design/fermilab-design-2015-01.pdf
- PIP-II Conceptual Design Report, FERMILAB-DESIGN-2017-01 (DOI 10.2172/1346823) — https://lss.fnal.gov/archive/design/fermilab-design-2017-01.pdf
- PIP-II Final Design Report, FERMILAB-DESIGN-2021-01 — https://lss.fnal.gov/archive/design/fermilab-design-2021-01.pdf (paywalled by Cloudflare; contents reconstructed from conference papers below)
- Pathak, Saini, Pozdeyev, "Final Physics Design of PIP-II" (2024) — https://arxiv.org/abs/2405.20953
- Saini et al., "Beam Dynamics Updates of the PIP-II 800 MeV SC Linac" (defines current 9×4 LB650 baseline) — https://lss.fnal.gov/archive/2019/conf/fermilab-conf-19-295-td.pdf
- SRF2021 overview MOOFAV05 (performance-goals + cavity tables) — https://proceedings.jacow.org/srf2021/papers/moofav05.pdf
- LLRF system paper (current QL/bandwidth table) — https://arxiv.org/abs/2311.00900

---

## 1. Overall Machine Parameters

| Parameter | Value | Notes |
|---|---|---|
| Species | H⁻ | Charge-exchange injection into Booster via foil |
| Ion source energy | 30 keV | DC source, 2 mA nominal / 15 mA max |
| RFQ output | 2.1 MeV ± 1% | 162.5 MHz CW |
| Final kinetic energy | **800 MeV** delivered; **833 MeV** design reach | All SRF at design gradient gives 833 MeV margin |
| Bunch frequency | **162.5 MHz** | All RF harmonics: 162.5 / 325 / 650 MHz |
| Peak (in-pulse, pre-chop) current | 5 mA from RFQ | Front end rated to 10 mA for upgrades |
| Average in-pulse current (post-chop) | **2 mA** | "averaged over a few µs" |
| Max bunch intensity | 1.9×10⁸ /bunch (≈30 pC) | = 5 mA at 162.5 MHz |
| Pulse length | **0.54 ms of beam / 0.55 ms window** | CDR table: 0.54 ms; injection time 0.55 ms. Both published; 2 mA × 0.54 ms = 6.7×10¹² ✓ |
| Repetition rate | **20 Hz** ✓ verified | Booster upgraded 15→20 Hz as part of PIP-II |
| Particles per pulse | 6.7×10¹² injected; 6.5×10¹² extracted from Booster | |
| Beam power | ~17 kW to Booster (pulsed); **1.6 MW capability at CW** (2 mA × 800 MeV); 1.2 MW on LBNF target from MI | |
| RF mode | CW RF with pulsed beam initially; fully CW-compatible | All SSAs and cryomodules CW-rated |
| Duty factor (pulsed) | 1.1 % | 0.55 ms × 20 Hz |
| Operating temperature | 2 K (2.5 kW @ 2 K plant, 50% margin) | |
| Total linac length | **215 m** (incl. warm front end + upgrade slots) | https://arxiv.org/abs/2311.05456 |

**Chopping (MEBT bunch-by-bunch chopper):** removes **~60% of bunches** (5 mA → 2 mA; CDR says "60–80% per pre-programmed timeline"). The pattern is **aperiodic and programmable**, not a fixed n-of-m: 162.5 MHz is not a harmonic of the Booster injection RF (**44.704 MHz**, h=84; 162.5/44.7 ≈ 3.635 bunches per bucket), so the chopper keeps only bunches that land within the useful phase of each 44.7 MHz bucket and also carves the Booster extraction-kicker gap. Demonstrated at PIP2IT: 500 V kicker swing, ~44 MHz average switching rate, 0.55 ms bursts at 20 Hz, extinction 5×10⁻⁴ (spec 10⁻³). Sources: https://arxiv.org/pdf/1806.08750, https://www.osti.gov/biblio/1468406, https://proceedings.jacow.org/ipac2021/papers/thpab324.pdf

**Booster injection:** 800 MeV H⁻ on **600 µg/cm² carbon stripping foil**, **285 turns** over 0.55 ms (CDR: 292; older RDR: 315 — use 285), ORBUMP chicane displaces closed orbit ~44 mm, transverse phase-space painting. https://proceedings.jacow.org/ipac2021/papers/wepab216.pdf

---

## 2. Lattice Summary Table (current baseline, 2019 re-baseline onward)

| Section | f (MHz) | E in → out (MeV) | CMs | Cavities | Focusing elements | Length (~) |
|---|---|---|---|---|---|---|
| LEBT | DC | 0.03 → 0.03 | — | — | 3 solenoids (0.62 T pk) | 2.0 m |
| RFQ | 162.5 | 0.03 → 2.1 | — | 4-vane, 4 modules | (RFQ internal) | 4.45 m |
| MEBT | 162.5 | 2.1 | — | 3 QWR bunchers | ~25 quads: 2 doublets + 7 triplets (PIP2IT final: 5 triplets) | **14 m** (PIP2IT was ~10 m) |
| HWR | 162.5 | 2.1 → 10.3 (10.0 reach-set) | 1 | 8 (β_opt 0.112) | 8 SC solenoids, period (s·c) | 5.93 m |
| SSR1 | 325 | 10 → 32 (nominal ~35) | 2 | 16 (8/CM, β_opt 0.222) | 8 SC solenoids (4/CM, pattern c·s·c) | 2 × 5.57 m + gaps ≈ 13 m (~) |
| SSR2 | 325 | 32 → 177 (nominal 185) | 7 | 35 (5/CM, β_opt 0.47) | 21 SC solenoids (3/CM, pattern s·cc·s·cc·s·c) | 7 × ~6.2 m + gaps ≈ 47 m (~) |
| LB650 | 650 | 177 → 516 (nominal ~500) | 9 | 36 (4/CM, 5-cell, β_G 0.61) | ~9–10 warm quad doublets (1 between CMs) | 9 × 5.52 m + doublet slots ≈ 60 m (~) |
| HB650 | 650 | 516 → 833 (800 delivered) | 4 | 24 (6/CM, 5-cell, β_G 0.92) | ~4–5 warm quad doublets + 4 empty doublet periods reserved for 1.2 GeV upgrade | 4 × 9.92 m + slots ≈ 50 m (~) |
| **Total SRF** | | 2.1 → 833 | **23** | **119** | 37 solenoids + ~15 doublets | SC section ≈ 176 m (~), linac 215 m |
| BTL | — (650 MHz debuncher) | 800 (transport) | — | 1 warm debuncher, 1.3 MV | FODO, ~11.8 m cells, 90°/cell; 32 dipoles (~), F/D quad circuits | **308 m** |

Per-section lengths marked (~) are assembled from published CM lengths + insertion allowances; no clean per-section length table is public (it lives in the TDR-internal lattice files). Verified anchor points: laserwire station coordinates put MEBT station at 18.7 m, HWR at 25.4 m, HB650 CM4 at 192.9 m (https://arxiv.org/abs/2310.02853).

**Important historical trap:** RDR/CDR-era lattice was **25 CMs / 116 cavities with LB650 = 11 CMs × 3 cavities**. The current baseline is **23 CMs / 119 cavities with LB650 = 9 CMs × 4 cavities** (FERMILAB-CONF-19-295-TD; confirmed by LLRF paper Fig. 2). Don't mix the two.

### 2.1 Warm front end details

**LEBT** (2 m): D-Pace (TRIUMF-type) filament volume-cusp H⁻ source, 30 keV, 15 mA DC capability; final design has **2 sources + 30° switching dipole**. 3 solenoids (0.62 T peak at 300 A, ∫B² ≤ 0.034 T²·m), each with x/y dipole steering coils (0.5 mT·m at 15 A). **LEBT chopper** = electrostatic kicker (plates 16 cm long, 32 mm gap; −5 kV blocks beam; rise/fall <100 ns) — primary MPS beam-inhibit device. Transport is **partially neutralized**: fully neutralized to mid-solenoid-2, un-neutralized over last ~1 m (chopper→RFQ). Measured LEBT-exit emittance 0.13 µm rms norm at 5 mA. https://arxiv.org/abs/1704.08744

**RFQ** (4.45 m, LBNL): 162.5 MHz CW, 4-vane brazed OFHC, 4 modules; **vane voltage 60 kV** (conditioned to 65); wall losses ~80 kW, driven by 2 × 75 kW SSAs; **transmission 98–99%** measured; output εt = 0.17–0.22 µm at 5 mA. https://accelconf.web.cern.ch/pac2013/papers/wepma21.pdf, https://arxiv.org/abs/1709.07516

**MEBT** (14 m final design; 9 sections, regular period 1140 mm): 3 identical **162.5 MHz quarter-wave bunchers, 70 kV nominal effective voltage** (β=0.0668, operated to 90 kV), run at −90° (pure bunching). ~25 BARC EMQ quads in 2 doublets + 7 triplets, each group with bolted-on BPM + x/y corrector pair. **Chopper:** two travelling-wave kickers (0.5 m plates, 16 mm gap, phase velocity 20 mm/ns) 180° apart; production choice is the **200 Ω helical kicker, 0→500 V in ~2 ns** (IPAC21 THPAB324 spec: 2 ns rise/fall, 4 ns minimum pulse width; bunch spacing 6.15 ns); deflection spec >7 mrad, 6σ separation at absorber. **TZM absorber at 29 mrad grazing incidence, rated 21 kW CW.** 4 scraper sets × 4 jaws (~90° phase advance apart), 75–100 W each. https://proceedings.jacow.org/hb2018/papers/thp1wc03.pdf, https://proceedings.jacow.org/ipac2018/papers/tupaf076.pdf

### 2.2 Cavity parameters (SRF2021 Table 2 + RDR)

| Cavity | β_opt (β_G) | f (MHz) | E_acc @ β_opt | V_eff/cav | L_eff | Aperture ⌀ | Q₀ spec |
|---|---|---|---|---|---|---|---|
| HWR | 0.112 (0.094) | 162.5 | 9.7 MV/m | 2.0 MV | 0.207 m | 33 mm | 0.5–0.85×10¹⁰ (meas. 1.3×10¹⁰) |
| SSR1 | 0.222 (0.186) | 325 | 10 MV/m | 2.05 MV | 0.205 m | 30 mm | 0.6–0.82×10¹⁰ |
| SSR2 | 0.47 (v3.1 design 0.472; pre-2019: 0.475) | 325 | 11.4 MV/m | ~5 MV | 0.438 m | 40 mm | 0.82×10¹⁰ |
| LB650 5-cell | 0.647 (0.61) | 650 | 16.8 (RDR 15.9) MV/m | 11.9 MV | 0.746 m | 83 mm | 2.4×10¹⁰ |
| HB650 5-cell | 0.971 (0.92) | 650 | 18.7 (RDR 17.8) MV/m | 19.9 MV | 1.12 m | 118 mm | 3.3×10¹⁰ |

HWR extras: E_pk 44.9 MV/m, B_pk 48.3 mT, R/Q 275 Ω, G 48 Ω, donut drift tube cancels quadrupole term. Spoke cavities have a residual quadrupolar RF kick — compensated with solenoid-package skew/normal corrector coils (relevant if you model 3D cavity fields). First cavity of each section runs below nominal voltage for longitudinal matching; the very first HWR runs at ~half voltage.

### 2.3 BTL (Beam Transfer Line)

308 m, FODO (cell ≈ 11.8 m, 90° H / 111° V per cell): two achromatic arcs (4 arc modules of 4 cells; total bend 217°) + 8-cell dispersion-free straight + phase trombone (sets collimator→foil phase advance = nπ). Dipoles: 2.45 m, 6.78° each, **B ≈ 0.24 T at 800 MeV — deliberately below the 0.277 T Lorentz-stripping limit** (10⁻⁸/m at 1 GeV). Quads L = 0.2 m, G ≈ 6–7 T/m. **650 MHz normal-conducting debuncher in cell 3, 1.3 MV gap voltage**, restores rms dp/p from 4.2×10⁻⁴ (space-charge growth over the line) to 2×10⁻⁴. Transverse collimation in both planes ahead of the foil; momentum collimation ±1.5×10⁻³ in the first arc (RDR-era). https://arxiv.org/abs/2405.20953, https://arxiv.org/abs/2312.09026, https://arxiv.org/abs/2405.19515

---

## 3. Instrumentation

**BPMs — 126 total (392 signals)**, all four-button, one at every focusing element (https://arxiv.org/abs/2509.15388):

| Region | Count | Aperture | Notes |
|---|---|---|---|
| MEBT | 12 | 28.5 mm | 20 mm buttons, FRIB-like; 4 BPMs in chopper region run two-trajectory mode |
| HWR (cold, on solenoids) | 8 | 36 mm | |
| SSR1 (cold) | 8 | 33 mm | |
| SSR2 (cold) | 21 | 43 mm | |
| 650 MHz warm sections | 20 | 45 mm | on quad doublets |
| BTL | 56 + 1 | 45 mm | single-plane (x at F, y at D quads) |

Measure x, y, **phase vs 162.5 MHz reference (→ TOF energy)**, intensity; 3rd-harmonic channel gives relative bunch length. Specs: 10 µm position, 0.3° phase resolution, 1° phase stability, 1% intensity. µTCA.4 electronics, White Rabbit timing. A movable TOF BPM is used for absolute energy.

**BLMs:** ion chambers (µs response) near focusing elements; fast PMT/scintillators (~10 ns) concentrated below ~100 MeV where ion chambers are insensitive to H⁻ loss radiation; neutron detectors at CM midpoints; ~100 m-long Ar/CO₂ **Total Loss Monitor** tubes enforcing W/m limits. Total channel count not public (lives in the 2023 BI FDR). Crucially, **low-energy loss detection is by differential beam current**, not radiation: PIP2IT MPS used 3 ACCTs + 4 ring pickups + dump current, ~3% loss resolution, **beam-off < 10 µs** (https://arxiv.org/abs/2209.01227).

**Profile/emittance:** **12 laserwire (H⁻ photodetachment, 1064 nm) stations + 1 laser emittance station** at: MEBT (18.7 m), HWR exit (25.4 m), SSR1-CM1, SSR2-CM2/4/6, LB650-CM1/3/6/9, HB650-CM2/4 (192.9 m) (https://arxiv.org/abs/2310.02853). Wire scanners only in MEBT and BTL (broken-wire risk forbids them near SRF; PIP2IT HEBT had 2). 2 Allison scanners (LEBT 30 keV, MEBT 2.1 MeV). Fast Faraday cup + RWCM for bunch shape/extinction at 2.1 MeV.

**Current:** DCCTs (CW) + ACCTs/toroids (pulsed) at section boundaries (PIP2IT: 5 monitors — LEBT×2, MEBT×2, SSR1 exit); Faraday cups/beam stops in LEBT and dump lines.

---

## 4. RF Systems

**One solid-state amplifier per cavity, all CW-rated** (https://arxiv.org/abs/1803.08211, https://arxiv.org/abs/2510.21036):

| System | SSA rating | With-beam need at 2 mA |
|---|---|---|
| RFQ | 2 × 75 kW (Sigma Phi) | ~80 kW wall + beam |
| Bunchers (×3) | 3 kW | — |
| HWR | 7 kW | 4.5 kW |
| SSR1 | 7 kW | 4.1 kW |
| SSR2 | 20 kW | 11.9 kW |
| LB650 | 40 kW | 29 kW |
| HB650 | 70 kW | 40.7 kW |

**Loaded Q / half-bandwidth (current baseline, arXiv:2311.00900 Table 1 — verified):**

| Cavity | Q_L | f₁/₂ = f₀/2Q_L |
|---|---|---|
| RFQ | 1.5×10⁴ | 5.5 kHz |
| Buncher | 1.0×10⁴ | 8.1 kHz |
| HWR | 2.32×10⁶ | 35 Hz |
| SSR1 | 3.02×10⁶ | 53.8 Hz |
| SSR2 | 5.05×10⁶ | 32.2 Hz |
| LB650 | 1.036×10⁷ | 31.4 Hz |
| HB650 | 9.92×10⁶ | 32.8 Hz |

(Older RDR values — HWR 2.7×10⁶, SSR1 3.7×10⁶, SSR2 5.8×10⁶, LB650 1.13×10⁷ — still circulate; use the LLRF-paper set.) Note: cavity bandwidths (~30–54 Hz) are comparable to the detuning budget — this is the central LLRF challenge.

**LLRF:** field stability spec **0.06% amplitude / 0.06° phase rms** (beam-energy stability 0.01%); PIP2IT achieved 0.01%/0.006° on HWR. Architectures: FNAL Arria10 I/Q controller (WFE+HWR); LBNL Marble/LCLS-II-derived SEL controller with SELAP mode (all 325/650 MHz cavities). Adaptive feedforward beam-loading compensation is mandatory in pulsed mode (beam loading raises power 1.3–1.4×). Phase reference line: coherent 162.5/325/650 MHz generated by successive frequency doubling, run in-tunnel for thermal drift cancellation (https://arxiv.org/abs/2510.12960).

**Detuning/tuners:** RF power budget assumes **20 Hz peak detuning** (microphonics + residual LFD); PIP2IT measured <10 Hz pk-pk microphonics. Tuners: HWR — pneumatic (He pressure) slow tuner only; SSR1/SSR2/LB650/HB650 — **slow stepper (double-lever, ~0.03–0.6 Hz/step) + fast piezo** (2× PI PICMA, ~985 Hz/100 V at 2 K, ~0.5 Hz resolution) for microphonics and pulsed Lorentz-force-detuning compensation. df/dP (HWR) = 1.4 kHz/atm. https://lss.fnal.gov/archive/2022/conf/fermilab-conf-22-805-td.pdf

---

## 5. Magnets and Correctors

**SC solenoids (37 total: 8 HWR, 8 SSR1, 21 SSR2):** spec is written as focusing integral, not field — SSR1 lens **∫B²dL = 4 T²·m** (6.8–7 T on axis at ~65 A max, quench margin 35%), SSR2 **5 T²·m** (~6.0 T center field). "6 T-class" is a fair summary; a flat "6 T spec" is an oversimplification. Each package: main coil + 2 bucking coils (fringe <5 G at cavity) + **4 independently powered corrector windings** (x/y dipole ± skew-quad function for spoke-kick compensation), **corrector strength 2.5 mT·m** (~5 mrad at 10 MeV), field-integral nonuniformity ≤5% within r=12 mm; BPM bolted to every lens. Alignment 0.2 mm / 1 mrad rms. https://www.osti.gov/pages/servlets/purl/1294513

**Warm quads:** MEBT — BARC EMQs (few T/m at Bρ = 0.44 T·m; exact gradients unpublished), corrector pair after each group. 650 MHz sections — one doublet between CMs, single quad family; integrated gradient ~3 T (~, appears in baseline-optics text but not verified as a formal spec — treat as approximate), x/y correctors + BPM in every doublet package. BTL — L=0.2 m, G ≈ 6–7 T/m, serial F/D circuits, H/V corrector after each quad.

**Corrector count rule of thumb for your model:** one x/y corrector pair + BPM per focusing element (every solenoid, every MEBT quad group, every doublet, every BTL half-cell) — that reproduces the published orbit-correction scheme.

---

## 6. Beam Physics Essentials for Simulation

**Emittance budget (rms normalized, mm·mrad; RDR Table 2.2 + PIP2IT measurements):**

| Location | Transverse (spec) | Longitudinal (spec) | Measured (PIP2IT) |
|---|---|---|---|
| RFQ exit | ≤0.20 | ≤0.28 (0.88 eV·µs) | 0.17–0.22 |
| MEBT exit | ≤0.23 | ≤0.31 | ~0.20 (Allison) |
| ~16 MeV (SSR1 exit) | 0.25 | 0.4 | 0.23–0.28 tr / 0.29 long |
| Linac exit (800 MeV) | ≤0.30 | ≤0.35 (~1.1 keV·ns) | — (σ_t ≈ 4 ps) |

The commonly quoted "0.25 mm·mrad" is the mid-linac spec; use ~0.2 µm at RFQ exit as the input. 2024 re-optimized design shows only 3–4% emittance growth end-to-end (older baseline: ~21% transverse, mostly low-energy emittance exchange).

**Optics/Twiss:** rms transverse size ≤3 mm everywhere in the SC linac; apertures fit 10–12σ above SSR2, tightest in HWR/SSR1 (33/30 mm cavity bores); the 650 MHz sections are limited by the 46 mm quad pipe, not the 83/118 mm cavity bores. Fixed inter-CM collimators (5 mm under downstream aperture) in the spoke sections.

**Longitudinal:** design rule — synchronous phase starts at **φs = −30° at the SC linac entrance, |φs| decreasing ∝ 1/√E** (roughly −30° HWR → high-teens/−20s° in HB650; exact per-cavity values published only as figures: RDR Fig. 2.24, arXiv:2405.20953 Fig. 2c). MEBT bunchers at −90°. First cavity of each section detuned/de-rated for matching. Design constraints: zero-current phase advance σ₀ < 90°/period; adiabatic phase-advance-per-meter variation across section transitions; avoid σ_t = n·σ_z/2 parametric resonances; Hofmann-chart working point k_x/k_z ≈ 1.3; longitudinal acceptance > 6σ.

**Space charge:** tune depression kept > 0.5; dominant in MEBT/HWR (2.1 MeV RFQ energy chosen for this); emittance exchange negligible above ~30 MeV; in the BTL it doubles dp/p over 308 m (hence the debuncher). At 2 mA this is mild — a 3D PIC or even 2.5D treatment at 5 mA peak in the front end, frozen/envelope above ~100 MeV, is defensible.

**H⁻ loss mechanisms** (https://arxiv.org/abs/2103.16195, RDR §2):
- **Criterion:** 1 W/m generic hands-on limit; PIP-II adopts **~0.1 W/m** (≈5×10⁻⁸/m fractional at CW, 5×10⁻⁶/m pulsed).
- **Intrabeam stripping** — dominant SC-linac mechanism (SNS: Shishlo PRL 108, 114801); PIP-II design keeps it <0.1 W/m even at CW, <10 W integrated.
- **Residual gas stripping** — σ ≈ 10⁻¹⁹ cm² (H₂, 0.8 GeV); vacuum ≤10⁻⁸ Torr H₂-equivalent.
- **Lorentz (magnetic) stripping** — τ = (A/E)·exp(B/E), A = 2.47×10⁻⁸ V·s/cm, B = 4.494×10⁷ V/cm; sets BTL dipole limit 0.277 T (at 800 MeV, 0.24 T operating → 3×10⁻¹³/m, negligible); Booster chicane must stay <0.4 T.
- **Blackbody photodetachment** — explicitly negligible at 0.8 GeV / 300 K (becomes a 0.1 W/m issue only above ~2 GeV).
- MPS: beam-off in <10 µs via ion-source inhibit + LEBT chopper.

---

## 7. Simulation Codes

**Used for PIP-II design:** **TraceWin** (primary end-to-end with 3D field maps and error/fault-compensation studies — validated against PIP2IT to ~1.5% in energy and ~10–20% in emittance), **TRACK** (ANL, cross-benchmark), GenLinWin (lattice generation), PARMTEQM/Toutatis (RFQ), OptiM (envelope fits), **PyORBIT** (Booster injection: full 6D with foil scattering, painting, space charge, impedance — arXiv:2405.20998). The 2024 design round added ML optimization (GA/CNN/RL solenoid tuning).

**Open-source options:** PyORBIT/PyORBIT3 (injection end), ImpactX (LBNL, GPU — strongest open candidate for SC-linac end-to-end), Xsuite (GPU contexts, ring-oriented), hpsim (LANL GPU ion-linac). A custom envelope/transfer-matrix model is entirely adequate for a 2 mA control-room-style virtual machine: per-cavity thin-gap energy/phase kicks (V_eff, φs from §2.2/§6), solenoid + quad matrices, KV-envelope space charge in the front end — this reproduces the BPM/phase/TOF observables the instrumentation layer publishes.

---

### Residual uncertainties (not publicly published)
- Exact per-cavity synchronous phase and quad/solenoid strength tables (TDR-internal lattice files; figures only in open literature).
- Total BLM channel count and production wire-scanner count (internal FDRs at indico.fnal.gov events 60510/60682).
- MEBT quad gradients in T/m (functional-requirement specs not open).
- Per-section physical lengths to better than ~±10% (assembled from CM lengths + insertion allowances here).
