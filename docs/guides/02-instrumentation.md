# 02 — Instrumentation pages

*(Physics of each instrument: see the [device reference](instrumentation-device-guide.md).)*

## Orbit
x/y orbit across all BPMs (device-name axis), TOF energy trace, and the
corrector budget bars (who is working hardest). **Run BBA** launches
beam-based alignment: quad-shunt measurement of each BPM's electrical
offset so orbit correction steers to magnetic centers. Auto-tune (banner)
is the SVD stabilizer: 2 s cadence, ±0.3 A steps, 250 µm deadband —
it recovers perturbations (~20 s for 2.5 A) but is deliberately deaf to
noise-level errors; loss-based steering (studies) is the optimizer.

## Losses
Every BLM vs its MPS threshold (staircase overlay from the live
threshold table). Log y. Use with the MPS page after any trip; the
postmortem waveforms (Waveforms page) hold the last pulses before it.

## Profiles
- **Single scans**: pick any wire scanner *or laserwire* (below the
  separator), set points and pulses-per-point, Start scan. Wires show
  true distribution + tails (macro tracker); laserwires show clean
  envelope Gaussians ⊗ 0.1 mm laser (non-invasive).
- **Cycle scans**: steps through *every* wire and *every* laserwire,
  one of each at a time, with separately configurable points/ppp.
  Ends with the σ(s) summary plot: laser σx/σy and wire σx along the
  machine — measured envelope vs model.
- **3D cloud**: choose the station where the GPU tracker dumps its
  30k-particle cloud (also drawn on the dashboard synoptic).
- Emittance vs s from the deep pass plots alongside.

## Waveforms
Intra-pulse (1000 samples / 0.55 ms) waveforms: toroids, BLMs, selected
RF cavities (checkable tree, Cavities group). On any trip a postmortem
snapshot freezes the last pulses — the first place to look after a trip.

## Bunch Monitor (RWCM)
Scope-style reconstruction of the bunch train (Gaussians on the 6.15 ns
bucket grid) and per-bucket charge bars for MEBT:WCM1 (post-chopper) and
BTL:WCM1. **log scale** exposes the 10⁻⁴ chopped-bunch extinction floor.
The **Pattern generator** row programs the chopper: `duty`, `booster`
(turn length + extraction notch) or `custom` bitmask → Program. Blue
markers overlay the programmed pattern; the verification readout goes
red naming mismatched buckets (e.g. a stuck pulser). Reprogramming is an
intensity change — re-baseline the MPS after.

## Strip Tool
Free-form time-series plotting of any channels at 20 Hz for drift
watching and correlation hunting.
