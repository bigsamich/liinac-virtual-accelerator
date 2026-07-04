# PIP-II Virtual Accelerator — 100-Study Campaign Report

**Date:** 2026-07-04 · **Studies executed:** 100 · **KB findings:** 106 (7 distilled insights, 10 empirical limits found by tripping)

## Machine state after the campaign
- 800.0 MeV, T = 99.5%, worst-BLM ~5 W/m (was 21 at campaign start; 4x headroom over the BTL activation constraint)
- Loss-based steering applied in SSR1/SSR2/LB650 (x and y), baked into the golden snapshot; every subsequent survey confirms the machine has converged (best = current settings)

## The ten defining machine truths
1. Space-charge matching U-curve: matched at exactly 5.0 mA; running below nominal is worse than above (175 W/m at 4.0 vs 27 at 5.0)
2. BTL entrance collimation is the governing activation constraint (strict 1 W/m at 800 MeV; front-end phase errors reach it through energy spread, invisible in transmission)
3. Front-end longitudinal knife-edge: bunchers hold ±1-3 deg; the capture chain amplifies (HWR:CAV1 amp scan trips at ±8%)
4. Section-boundary cavities are forgiving; end-of-linac phase trim is wide open (the right place for energy corrections)
5. Loss-based steering beats BPM-based below the ~250 um electrical-offset floor (21 -> 4.5 W/m where SVD had converged)
6. Solenoid tolerances: HWR +2%/-4.5%, SSR1 +/-3%, SSR2 +/-3%; quads: MEBT most sensitive (2x LB650), LB650 single +6%, doublet-differential +3%
7. Drift: +0.10 W/m per minute at 21 W/m quiescent, ~flat when optimized — baselines stale hourly on a mis-steered machine
8. Emittance growth 0.250 -> 0.279 um (x) over 4 -> 5.5 mA, eps_y flat — matches the published PIP-II budget
9. Intensity changes in EITHER direction need MPS re-baselining (the whole loss pattern scales/shifts); rebaseline-per-plateau ramps reach 3 mA delivered (+50%)
10. TOF energy stability 800.01 +/- 0.23 MeV (0.03%) — at the published spec

## Distilled insights on record
- **insight-btl-entrance-constraint**: MACHINE CONSTRAINT: MEBT buncher phase must hold within ~1 deg of -90. A 2 deg shift leaves transmission ~99.3% but raises linac-exit energy spread, and the BTL ENTRANCE collimation (BTL:BLM1, 800 MeV, strict 1 W/m activation limit) scrapes 10x more. The debuncher sits downstream and cannot protect it. Any front-end longitudinal study will trip the BTL before transmission shows anything.
- **insight-sc-matching-u-curve**: MACHINE CONSTRAINT: the lattice is space-charge matched at 5.0 mA — losses form a U-curve in current (175 W/m at 4.0, 27 at 5.0, 40 at 5.5). Any intensity change degrades optics; running BELOW nominal is worse than slightly above. Cross-validated by the earlier down-ramp study (191 W/m at 4).
- **insight-drift-rate**: QUANTIFIED: quiescent losses creep +0.10 W/m per minute (~6 W/m/hour) from device drift at frozen setpoints; TOF energy holds 800.01 +/- 0.23 MeV (0.03%, at spec). This is why baselines stale in ~1 hour: schedule relearn accordingly.
- **insight-emittance-growth**: Emittance growth with current: eps_x 0.250 -> 0.279 um from 4 -> 5.5 mA (space charge), eps_y flat at 0.34 um. Matches published PIP-II scale (~0.25 um mid-linac).
- **insight-ssr1-bump-steering**: SSR1:C3 +0.4/+0.8 A with C5 opposite IMPROVES the as-built machine: losses 24 -> 15 W/m, orbit rms 1.20 -> 1.05 mm. Not a closed bump at this spacing — it is free steering the orbit correction has not exploited. Candidate golden update.
- **insight-ssr2-acceptance**: SSR2 local acceptance curve: losses grow smoothly ~20 W/m per amp of x-trim beyond 2 A (24 W/m at 0 -> 123 at 5 A), no hard edge within the +/-5 A supply range at current thresholds.
- **insight-loss-based-steering**: OPERATIONAL LESSON: loss-based steering beats BPM-based steering on this machine. The SVD orbit trim is floored at ~250 um by BPM electrical offsets, but opposing-corrector pairs tuned directly on BLM signals cut worst-BLM 21 -> 4.5 W/m (SSR1:C3/C5x +0.8/-0.8, SSR2:C4/C8 x +0.8/-0.8 and y -0.8/+0.8, LB650:C2/C6 y -0.8/+0.8, all applied and in golden). Losses see the TRUE orbit; BPMs see it plus their offsets. Survey pairs per section/plane when losses sit above ~10 W/m quiescent.

## Process capabilities proven
- NL -> AI plan -> validated execution -> per-step capture -> AI report, with the KB feeding both the planner and trip analysis
- Executor survival stack: settle-after-arm, errant-glitch retry, marginal-trip auto-rebaseline, reset->relearn escalation, trip-abort with restore — 21/21 completions in the final waves
- Apply-and-learn: survey -> auto-apply winners -> re-baseline -> golden; the machine improved 4.7x through its own studies