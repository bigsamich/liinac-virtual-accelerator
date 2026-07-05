# PIP-II Virtual Accelerator — User Guide

A complete virtual Fermilab PIP-II linac: 800 MeV H⁻ superconducting
accelerator with physics-based beam dynamics, SRF cavities, full
instrumentation, machine protection, utilities, an AI operations
assistant, and a self-improving beam-study program — running as Docker
microservices with native (PyQt6), browser, and phone interfaces.

## Quick start
```
make up        # start the 9-service stack (docker compose)
make gui       # native control-room GUI (host, GPU-accelerated 3D)
make reset     # nuclear reset: fresh machine in ~90 s, prints MACHINE READY
make test      # run the test suite
```
- Browser GUI:  http://gb10:6080/vnc.html   (same GUI, streamed)
- Phone:        http://gb10:6081            (status, trends, studies, ask)

## The machine in one paragraph
H⁻ from a 30 keV source → RFQ (2.1 MeV, 162.5 MHz) → MEBT with a
bunch-by-bunch chopper → SRF sections HWR → SSR1 → SSR2 (325 MHz) →
LB650 → HB650 (650 MHz) to 800 MeV → Beam Transfer Line (8 dipoles) to
the dump. 20 Hz × 0.55 ms pulses, 5 mA pre-chop / ~2 mA delivered,
bunches every 6.15 ns. 123 cavities, 174 magnets, 74 BPMs, 46 BLMs,
9 BCMs, 2 RWCMs, 14 wire scanners, 12 laserwires, 15 cryomodules.

## If you only remember five things
1. **RESET PERMIT** (banner) clears a trip; **RESCUE** cold-restarts to
   the golden state; `make reset` rebuilds the world.
2. Any **intensity change** (source, chopper duty, bunch pattern) needs
   an MPS re-baseline: MPS page → Relearn, or use ramp studies with
   `rebaseline` on.
3. The **ask bar** (bottom of every page, and the phone) answers from
   the machine's own measured knowledge — ask before you turn a knob.
4. The front end's **buncher phases are the knife edge** (±1–3°);
   everything else has comfortable single-knob margin.
5. Studies are the way to learn anything: **Studies page → describe it
   in English → Plan → Queue → RUN.** Results feed the knowledge base
   automatically.

## Guide index
| Doc | Covers |
|---|---|
| [01 Dashboard & 3D](01-dashboard-3d.md) | main screen, synoptic, 3D controls |
| [02 Instrumentation](02-instrumentation.md) | Orbit, Losses, Profiles, Waveforms, Bunch Monitor, Strip Tool |
| [03 RF & Magnets](03-rf-magnets.md) | RF page, tune-up, Magnets, Source & LEBT |
| [04 Operations](04-operations.md) | Studies, Training, Snapshots, MPS |
| [05 Machine](05-machine.md) | Physics parameters, Utilities (cryo/LCW) |
| [06 Remote & mobile](06-remote-mobile.md) | browser GUI, phone dashboard |
| [07 Architecture & AI](07-architecture-ai.md) | services, physics engines, LLM stack, extending |
| [Device & physics reference](instrumentation-device-guide.md) | every device: physics + model + measured findings |
