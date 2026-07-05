"""Laserwire (photodetachment) profile system — 12 stations along the SCL.

PIP-II design: the source laser is piped under vacuum to 12 beamline
stations, each with an insertable mirror and scan optics focusing the laser
to <100 um rms at the H- beam. The laser detaches the outer electron; the
electrons are bent up into a Faraday cup, giving a NON-INVASIVE transverse
profile — usable at full beam power where a solid wire would melt (which is
why the warm front end uses wires and the SC linac uses laserwires).

Measurement model vs the solid wire scanners:
- laserwire: envelope-true Gaussian convolved with the 0.1 mm laser focus,
  photodetachment (Poisson) statistics — clean rms, no tails, no beam loss.
- wire scanner: macroparticle histogram — real distribution incl. tails,
  but invasive and (in the SCL) thermally limited.
"""
from __future__ import annotations

LASER_RMS_MM = 0.10        # focused laser spot at the interaction point

# (name, section, fraction of section length)
_LAYOUT = [
    ("HWR:LW1", "HWR", 0.55),
    ("SSR1:LW1", "SSR1", 0.30), ("SSR1:LW2", "SSR1", 0.75),
    ("SSR2:LW1", "SSR2", 0.20), ("SSR2:LW2", "SSR2", 0.55),
    ("SSR2:LW3", "SSR2", 0.85),
    ("LB650:LW1", "LB650", 0.25), ("LB650:LW2", "LB650", 0.55),
    ("LB650:LW3", "LB650", 0.85),
    ("HB650:LW1", "HB650", 0.25), ("HB650:LW2", "HB650", 0.60),
    ("HB650:LW3", "HB650", 0.90),
]


def stations(lat) -> list[tuple[str, float]]:
    """Resolve the 12 stations to s positions [m] for this lattice."""
    secs = {s.name: s for s in lat.sections}
    out = []
    for name, sec, frac in _LAYOUT:
        s = secs[sec]
        out.append((name, s.s_start + frac * (s.s_end - s.s_start)))
    return out
