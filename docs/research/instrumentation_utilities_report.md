# PIP-II instrumentation & utilities — research pack (2026-07-05)

## Wall current monitors (RWCM)
- PIP2IT used **two Resistive Wall Current Monitors** with flat response
  10 kHz – ~4 GHz, resolving **individual bunches** (162.5 MHz structure,
  6.2 ns spacing, ~1 ns bunches).
- Primary mission: **bunch-extinction measurement of the MEBT bunch-by-bunch
  chopper at the 1e-4 level** — the chopper can remove bunches in any
  programmable pattern for Booster injection.
- Complemented by a Fast Faraday Cup for bunch-length measurement.

## Cryogenics
- One cryoplant, three temperature levels: **40 K** thermal shields,
  **4.5 K** intercepts, **2 K** (superfluid, ~31 mbar saturated) for
  cavities.
- **df/dp measured on pre-production SSR2: −3.2 … −3.6 Hz/mbar** — He bath
  pressure variation is the *lowest-frequency* microphonics component.
- Cryomodule design uses a room-temperature strongback; heat load from RF
  (dynamic) + static load sets liquid level/valve behavior.

## Low-conductivity water (LCW)
- Regulated **95 ± 1 °F (35 ± 0.6 °C)** at service buildings by 3-way
  valves around heat exchangers (Fermilab Main Injector practice).
- Electronics coupling (PIP-II BPM electronics development):
  **~2° phase drift per 6 °C** uncalibrated; active calibration reduces to
  0.2°. Phase-sensitive measurements (BPM phase → TOF energy) inherit LCW/
  rack temperature drift. RF multiplier temp-cos ~±2°/°F class.
- SSA gain/forward-power calibration also drifts with cooling water.

## Counts
- Full PIP-II: **126 BPMs** across WFE + SC linac + BTL; 5 current monitors
  in the injector chain (2 LEBT, 2 MEBT, 1 post-SSR1).

## Sources
- [Bunch Extinction Measurements at PIP-II Injector Test Facility](https://www.osti.gov/biblio/1834186)
- [Beam Dynamics Studies at the PIP-II Injector Test Facility](https://arxiv.org/pdf/2208.11753)
- [Cold Test Results of Pre-Production PIP-II SSR2 Cavities](https://arxiv.org/pdf/2411.17096)
- [Status of the PIP-II Cryoplant](https://lss.fnal.gov/archive/2022/conf/fermilab-conf-22-517-pip2-td.pdf)
- [Development of BPM electronics for PIP-II at Fermilab](https://arxiv.org/pdf/2509.15388)
- [Main Injector LCW control system](https://www.osti.gov/biblio/7858)
- [PIP-II BCM fault analyses & BPM linearity studies](https://arxiv.org/pdf/2410.18951)
