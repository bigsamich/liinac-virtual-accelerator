"""Bunch pattern generator (BPG): the MEBT chopper's programmable
bunch-by-bunch pattern at 162.5 MHz.

Modes (settings:chopper:main):
  mode = "duty"    — legacy: keep round(duty*10) of every 10 buckets
  mode = "booster" — Booster-injection structure: within each Booster turn
                     (`turn` buckets, default 306 ~ 1.88 us revolution) keep
                     a micro-pattern of round(duty*5)-of-5, with a `notch`
                     of empty buckets (default 60) for the extraction-kicker
                     rise at the end of every turn.
  mode = "custom"  — `pattern` is a 0/1 string (up to 1024 buckets),
                     repeated forever.

Fault hook: `stuck_bucket` >= 0 forces that bucket index (mod its period)
to PASS even when the pattern says chop — a failed chopper pulser, visible
on the RWCM and flagged by pattern verification.

`avg_duty()` is the single source of truth for the pattern's mean
transmission — the physics (beam current, loading) consumes it, so every
mode stays consistent with the envelope/RF models.
"""
from __future__ import annotations

import numpy as np


def _base_bits(st: dict, n: int, offset: int) -> np.ndarray:
    mode = str(st.get("mode", "duty"))
    duty = min(1.0, max(0.0, float(st.get("duty", 0.4))))
    idx = np.arange(offset, offset + n)
    if mode == "custom":
        pat = str(st.get("pattern", "1111000000")).strip()
        bits = np.array([c == "1" for c in pat], dtype=bool)
        if not len(bits):
            bits = np.ones(1, dtype=bool)
        return bits[idx % len(bits)]
    if mode == "booster":
        turn = max(20, int(float(st.get("turn", 306))))
        notch = min(turn - 1, max(0, int(float(st.get("notch", 60)))))
        keep5 = max(0, min(5, round(duty * 5)))
        micro = (idx % 5) < keep5
        in_notch = (idx % turn) >= (turn - notch)
        return micro & ~in_notch
    keep10 = max(0, min(10, round(duty * 10)))
    return (idx % 10) < keep10


def programmed_bits(st: dict, n: int, offset: int = 0) -> np.ndarray:
    """The OPERATOR-PROGRAMMED pattern (no hardware faults) — the
    verification reference."""
    return _base_bits(st, n, offset)


def pattern_bits(st: dict, n: int, offset: int = 0) -> np.ndarray:
    """The pattern the chopper ACTUALLY delivers (programmed + any
    hardware fault such as a stuck bucket)."""
    bits = _base_bits(st, n, offset)
    stuck = int(float(st.get("stuck_bucket", -1)))
    if stuck >= 0:
        period = {"custom": max(len(str(st.get("pattern", "")).strip()), 1),
                  "booster": max(20, int(float(st.get("turn", 306)))),
                  }.get(str(st.get("mode", "duty")), 10)
        idx = np.arange(offset, offset + n)
        bits = bits | ((idx % period) == (stuck % period))
    return bits


def avg_duty(st: dict) -> float:
    """Mean transmission of the programmed pattern (physics duty)."""
    return float(np.mean(pattern_bits(st, 4096)))
