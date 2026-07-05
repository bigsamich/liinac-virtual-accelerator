# 01 — Dashboard & 3D synoptic

## Top of screen (always visible)
- **Banner**: beam-permit LED + state, RESET PERMIT, RESCUE (cold
  restore to golden), Auto-tune orbit checkbox, autotune status.
- **Section strip**: colored per-section health chips — click any to
  open that section's page (local orbit/losses, device table, 3D view).
- **Status bar**: link LED, permit LED, pulse counter, W, T.

## Big values
Output energy (MeV), Transmission (%), Beam current at the BTL (mA),
Worst BLM (W/m, red above 1 W/m class), Pulse charge (µC), Pulse count.

## Plots row
- **Orbit x/y** — all 74 BPMs, device-name axis; crosshair readout.
- **BLM losses** — vertical: LEBT at top, BTL at bottom; x = W/m,
  auto-ranged to the worst loss.
- **BCM currents** — vertical histogram, machine order; the chopper cut
  is the visible step. Boundary transmission reads inline below
  (chopper boundary is exempt from the red threshold).

## 3D synoptic (bottom)
True floor plan (BTL bends included), solid geometry per element family
(orange cavities, blue quads, cyan solenoids, magenta dipoles, yellow
correctors, green BCM rings, pale-green BPM rings), plus live beam:
- green BPM dots ride the orbit (0.25 m displayed per mm),
- translucent tube = live 2σ envelope,
- red spikes = BLM losses (log height),
- beamline glow = local current,
- cyan/orange cloud = GPU macroparticle bunch at the selected station
  (choose on Profiles page).

**Controls**: drag = rotate, wheel = zoom **to the center point**,
middle-drag = pan. `zoom:` dropdown frames any section. **Triple-click**
snaps the center to the nearest element (named in the readout).
Top/Side/End/Iso presets. **ghost** checkbox: grey trail of the last
100 pulses of orbit. **Hover** anywhere: readout shows the nearest BPM,
BLM, BCM and powered element with live values — no floating clutter.

## Ask-the-machine (bottom bar, every page)
Type any question — status, "what happens if…", "why is X high" — and
the AI answers from the live snapshot + the measured knowledge base.
× collapses the answer.
