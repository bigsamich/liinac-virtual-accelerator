# SRF Cavity Physics & H⁻ Beamline Engineering — Fidelity Reference (v4b)

Verified research pack (20 claims audited against primary sources; 17
confirmed, 3 corrected). This document drives the v4b physical RF
implementation in `pip2va/services/rf_sim/cavity_model.py`.

## 1. Cavity envelope equation (Schilcher TESLA-1998-20 / Simrock & Geng)

dṼc/dt = −(ω½ − jΔω(t))·Ṽc + 2ω½·Ṽfor + ω½·R_L·Ĩb

- ω½ = ω₀/2Q_L (half-bandwidth), R_L = ½(r/Q)Q_L (circuit convention from
  linac-convention r/Q), P_for = |Ṽfor|²/((r/Q)Q_L)
- Beam term |Ĩb| = 2·I_DC·FF (FF≈1), phase from synchronous phase; PIP-II
  2 mA in-pulse → 4 mA RF fundamental
- Exact exponential discrete update (unconditionally stable):
  V[k+1] = e^{(−ω½+jΔω)Δt}·V[k] + (1−e^{(−ω½+jΔω)Δt})·V_ss,
  V_ss = ω½ R_L I_tot/(ω½ − jΔω)
- LLRF: proportional gain G_p ≈ 1000–1600, K_i ≈ 3×10⁶ rad/s, loop delay
  1.2–3 µs; closed-loop BW ~86 kHz. Gated feedforward for beam loading
  (P step 1.3–1.44×; mistimed FF → bipolar edge glitches).
- Fill/decay τ = 2Q_L/ω₀ ≈ 3.0–5.1 ms for all PIP-II SC sections — ≫ 0.55 ms
  pulse, hence CW RF with pulsed beam.
- Open-loop beam sag over the pulse ≈ (V_b/V)(1−e^{−T/τ}) ≈ 12% (SSR1);
  closed-loop residual ≤0.03%/0.03° (PIP2IT measured 0.008–0.029% /
  0.006–0.023°; spec 0.065%/0.065°).

### Verified cavity table (RDR + arXiv:2311.00900 + arXiv:2510.21036)

| Section | f₀ MHz | V_cav MV | r/Q Ω | Q_L | f½ Hz | τ ms | P_for kW (0→2 mA) | SSA kW |
|---|---|---|---|---|---|---|---|---|
| HWR | 162.5 | 2.01 | 275 | 2.32e6 | 35 | 4.5 | 2.6→4.5 | 7 |
| SSR1 | 325 | 2.05 | 242 | 3.02e6 | 53.8 | 3.0 | 2.0→4.1 | 7 |
| SSR2 | 325 | 4.99 | 296 | 5.05e6 | 32.2 | 4.9 | 6.4→11.9 | 20 |
| LB650 | 650 | 11.88 | 375 | 1.04e7 | 31.4 | 5.1 | 15.9→29.0 | 40 |
| HB650 | 650 | 19.95 | 609 | 0.99e7 | 32.8 | 4.9 | 24.3→40.7 | 70 |

## 2. Lorentz-force detuning (Liepe/Moeller/Simrock PAC2001 MPPH128)

Per mechanical mode m:
  Δω̈_m + (ω_m/Q_m)Δω̇_m + ω_m²Δω_m = −2π·k_m·ω_m²·E_acc²(t),  Δf_LFD = ΣΔf_m
Static limit Δf = −k_L·E_acc². Measured k_L [Hz/(MV/m)²]: HWR −1.5,
SSR1 −4.4, SSR2 −7.5, LB650 −0.8 (est), HB650 −1.6 (prototype measured).
Mechanical modes: 157 Hz (first longitudinal), 215 Hz (strongest), cluster
150–250 Hz; Q_m ~ 50–200 (inferred). Piezo: 650 MHz ±2.4–3.6 kHz@100 V,
FB usable to ~20 Hz, ~1 ms delay; HWR pneumatic only (±60 kHz window).
Slow tuner: 0.75–1.25 Hz/step (650), ~5 Hz/step (SSR1), 30 Hz hysteresis.
RF power penalty: ΔP/P = ¼(Δf/f½)².

## 3. Microphonics (LCLS-II arXiv:2208.06316, SRF2023 MOPMB081, PIP2IT)

Synthesis: Δf = (df/dp)·x_He(OU: τc 30–200 s, σ 0.03–0.1 Torr) + wandering
lines {16–21 Hz + harmonics, 30 Hz pump, 40–56 Hz Helmholtz (drifting), 60 Hz}
+ mech-mode-filtered broadband + Poisson bursts (×3–5, minutes).
df/dp: HWR 13, SSR1 4, SSR2 3.4, 650 ~2–5 Hz/Torr. Targets: rms 1–5 Hz,
peak/rms ≈ 5–6, peak ≤ 20–25 Hz (PIP-II power budget assumes 20 Hz peak).
PIP2IT HWR: 3–4 min period He-regulation oscillation.

## 4. Quench & trips

Hard quench: Q₀ collapses 2e10 → 1e5–1e6 over ~100 µs → field decays with
τ = 2Q_L,eff/ω ≈ 0.05–0.5 ms (visible inside the 0.55 ms window). Detector:
decay-constant discriminator (XFEL trips on ΔQ_L > 5e5). Soft quench: field
holds, heat load ×10–100 → cryo trip minutes later. Timescales: RF truncation
<100 ns; MPS abort 10 µs (PIP-II demonstrated); auto-restart 4–8 pulses;
beam-loss trip recovery ~40 s (SNS: 9 s off + 30 s re-ramp). Trip statistics:
CEBAF ln(rate) = A + B·G per cavity, B ≈ 0.5–1.5 /(MV/m), A = −12.63−6.10·B.
Field emission: Fowler–Nordheim I ∝ (βE)²e^{−6.83e9·φ^1.5/βE}, φ=4.3 eV,
β~100–300, onset 8–21 MV/m; radiation ∝ exponential in gradient.

## 5. Beam loading / matching

P_g = V²/(4(r/Q)Q_L)·{[1+(r/Q)Q_L·I·cosφs/V]² + [Δf/f½+(r/Q)Q_L·I·sinφs/V]²}
Q_L,opt = V/((r/Q)·I·cosφs); Δf_opt = −f₀(r/Q)I·sinφs/(2V) ≈ 5–20 Hz at 2 mA.

## 6. Beamline

- Alignment budgets: SC linac 0.5 mm rms transverse (cav+sol), BTL quads
  0.25 mm → 3.0/1.6 mm uncorrected orbit → 0.07/0.03 mm after SVD with 28
  BPM+corrector pairs/plane. Kick θ = G·L·d/(Bρ); amplification 5–30×.
- BPMs (arXiv:2509.15388): 126 total; 10 µm resolution, 0.1 mm accuracy,
  0.3° phase resolution, 1° stability; temp drift 2°/6 °C (0.2° self-cal);
  offsets vs magnetic center 0.1–0.5 mm (beam-based alignment removes);
  nonlinearity beyond ~¼ aperture (odd-polynomial map).
- TOF energy (arXiv:2509.14214): 2πfL/v = Δφ + 2πN;
  δEk/Ek = γ(γ+1)√[(δL/L)² + (δφ·βc/2πfL)²] → 0.08–0.19%/pair, 0.04% global.
- BTL dispersion: two achromatic arcs, D ~ 1–2 m; energy jitter 1e-4 →
  0.1–0.2 mm coherent x-jitter at arc BPMs only (operator signature);
  650 MHz/1.3 MV debuncher holds δp/p < 2e-4.

## 7. H⁻ loss physics (verified formulas)

- Intrabeam stripping (Lebedev arXiv:1207.5492):
  (1/N)dN/ds = N·σmax·√(γ²θx²+γ²θy²+θs²)·F/(8π²γ²σxσyσs),
  σmax = 4e-15 cm² = 4e-19 m²; F ≈ 1+0.155[(a+b+c)/√(3(a²+b²+c²))−1];
  SNS measured total SCL loss 2–3e-5 (H⁻), ~0.1 W/m PIP-II design basis.
- Residual gas (Plum arXiv:1608.02456): σ = 1e-19/β² cm²/atom (H),
  7e-19/β² (N,O); n = 3.3e8 cm⁻³ per 1e-8 Torr diatomic ×2 atoms.
  At 800 MeV, 1e-8 Torr: H₂ 9e-9/m; N₂ 6.5e-8/m.
- Field stripping (Keating): df/ds = (B/3.073e-6)·exp(−4.414e9/(βγc·B));
  800 MeV: 1e-8/m at 0.31 T; BTL runs 0.228 T.
- Blackbody: negligible at 0.8 GeV (3e-9/m at 1 GeV/300 K).

## 8. Virtual accelerator lessons (SNS/J-PARC/CLARA/SLAC Simulacrum/Twinac)

Same PV interface as real machine; noise + device dynamics on every channel;
latching interlocks with correct recovery timescales; fault injection for
off-normal training; interactive-speed model; network isolation.

## Implementation shortlist (v4b status)

1. Integrated cavity envelope ODE per pulse (exact exponential update) — DONE
2. Beam-loading transient + PI feedback + loop delay + gated FF — DONE
3. Dynamic LFD (2 mechanical modes/cavity) — DONE
4. Stochastic microphonics (OU He drift + wandering lines + bursts) — DONE
5. Physical quench (Q₀ collapse; field dies inside the window) + CEBAF
   gradient-dependent stochastic trips — DONE
6. BPM TOF energy + nonlinearity — future
7. Misalignments + SVD correction — done in v4a
8. Verified H⁻ loss coefficients (IBSt Lebedev + residual gas /β²) — DONE
9. BTL dispersion + debuncher signature — future
10. Field-emission radiation channel — future
