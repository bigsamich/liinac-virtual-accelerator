# 05 — Machine: Physics & Utilities

## Physics page
Live tuning of the physics engine: space-charge scale, IBSt scale,
residual-gas pressure, dispersion scale, macro-particle count and
station. Changes take effect next pulse. Useful for what-if studies
("how much of my loss is space charge?") — set scales back to 1.0 (or
RESCUE) when done.

## Utilities page
- **LCW**: supply temperature trend (35 ± 0.6 °C regulation cycle) and
  the live coupling readout — BPM phase, TOF-energy systematic, SSA
  calibration per °C. If the energy readout wanders on a ~20-min
  period, it's the water, not the beam.
- **Cryo**: all 15 cryomodule 2 K bath pressures (31 mbar nominal,
  plant breathing visible). df/dp couples pressure to cavity detuning;
  piezo tuners null static shifts (measured: ±3 mbar invisible).
- **Inject**: LCW offset (chiller degradation) and per-CM pressure
  offsets (plant excursion) with Apply/Clear — utility fault drills.
