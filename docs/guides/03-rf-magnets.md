# 03 — RF & Magnets

## RF page
Table of all 123 cavities: setpoints (amplitude MV, phase deg) with
limits, live readbacks (amp/phase/detuning/forward power), status
(TRIPPED red). Detuning plot with crosshair. **Phase scan tune-up**:
sweeps a cavity's phase, cosine-fits the downstream energy response,
and sets the crest-relative phase — the standard commissioning move.
Per-cavity `ff` (0–1) fades the beam-loading feedforward — a study knob
(the residual dip grows as (1−ff)·(V_b/V)/(1+G_p)).

What to know before touching RF (measured): mid-linac phases tolerate
±5° (even coherently per-section); the *front-end bunchers do not*
(±1–3° — they trip the BTL through energy spread). A dead cavity is
recoverable with neighbors at +15%. Pushing amplitude raises
field-emission x-rays (nearby BLMs) before quench. Cavity trips follow
the CEBAF law near the field limit; clear + re-ramp from the table.

## Magnets page
Solenoids, quads, correctors: setpoints with hard limits, readbacks,
trip status. Correctors show x/y trim pairs. Measured tolerances:
solenoids ±2–3%, quads ±3% (MEBT triplet is the exception — coherent
scaling is the sharpest knob on the machine), correctors ±0.5 A is
always safe at the optimized point. A drifting solenoid can be
counter-trimmed by a neighbor (beat cancellation).

## Source & LEBT page
Source current (0–15 mA), LEBT solenoids, chopper duty. The machine is
space-charge matched at exactly **5.0 mA** — below-nominal running is
worse than above (U-curve). To change intensity use a ramp study with
`rebaseline`, and couple the RFQ amplitude (+1.5% at 6 mA) — the
validated multi-knob recipe. The RFQ amplitude optimum is 1.01×design;
transmission cliffs below 0.97.
