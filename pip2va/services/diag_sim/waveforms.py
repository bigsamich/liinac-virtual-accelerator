"""Intra-pulse waveform synthesis: 1000 samples across the 0.55 ms pulse.

Real PIP-II instrumentation digitizes within the pulse; this module gives
every BPM/BLM/toroid a per-pulse waveform built from the pulse-level truth:

  common beam envelope  rise (~10 us) -> flat top with droop + source ripple
                        + chopper keep-fraction -> fall (~5 us)
  toroid   I(t)   envelope * measured current + noise floor
  BPM      x/y(t) mean orbit + head transient (beam-loading settle) +
                  intra-pulse drift + sample noise; phase & sum likewise
  BLM      L(t)   envelope * loss level + stochastic micro-bursts

All arrays are float32 of length N_SAMPLES; the time axis is t_ms().
"""
from __future__ import annotations

import numpy as np

N_SAMPLES = 1000
WINDOW_MS = 0.55
BEAM_MS = 0.54
RISE_US = 10.0
FALL_US = 5.0


def t_ms() -> np.ndarray:
    return np.linspace(0.0, WINDOW_MS, N_SAMPLES, dtype=np.float32)


class WaveformSynth:
    def __init__(self, rng: np.random.Generator | None = None):
        self.rng = rng or np.random.default_rng()
        self.t = t_ms()
        t_us = self.t * 1e3
        beam_us = BEAM_MS * 1e3
        rise = np.clip(t_us / RISE_US, 0.0, 1.0)
        fall = np.clip((beam_us - t_us) / FALL_US + 1.0, 0.0, 1.0)
        fall[t_us < beam_us - FALL_US] = 1.0
        self.gate = (rise * fall * (t_us <= beam_us)).astype(np.float32)

    def envelope(self, droop_frac: float = 0.02,
                 ripple_frac: float = 0.004) -> np.ndarray:
        """Per-pulse beam-current envelope (fresh ripple phase each call)."""
        droop = 1.0 - droop_frac * self.t / WINDOW_MS
        ph = self.rng.uniform(0, 2 * np.pi)
        f_khz = self.rng.uniform(3.0, 6.0)
        ripple = 1.0 + ripple_frac * np.sin(
            2 * np.pi * f_khz * self.t + ph)
        return (self.gate * droop * ripple).astype(np.float32)

    def toroid(self, i_ma: float, noise_frac: float = 0.002,
               floor_ma: float = 0.005) -> np.ndarray:
        wf = i_ma * self.envelope()
        wf += self.rng.normal(0.0, max(i_ma * noise_frac * 3.0, floor_ma),
                              N_SAMPLES)
        return np.maximum(wf, 0.0).astype(np.float32)

    def bpm(self, x_m: float, sum_ma: float, noise_um: float = 10.0
            ) -> np.ndarray:
        """Position waveform [m]: head transient + drift + per-sample noise."""
        head = self.rng.normal(0.0, 0.3e-3) * np.exp(
            -self.t / 0.04)                       # beam-loading settle ~40 us
        drift = self.rng.normal(0.0, 0.05e-3) * (self.t / WINDOW_MS)
        # per-sample noise so that the pulse average matches the 20 Hz value
        sigma = noise_um * 1e-6 * np.sqrt(N_SAMPLES / 2.0)
        if sum_ma < 0.05:                          # no beam: pure noise floor
            return self.rng.normal(0.0, 20 * sigma,
                                   N_SAMPLES).astype(np.float32)
        wf = x_m + (head + drift) * self.gate + self.rng.normal(
            0.0, sigma, N_SAMPLES)
        return wf.astype(np.float32)

    def blm(self, wpm: float, dark_wpm: float = 1e-3) -> np.ndarray:
        wf = wpm * self.envelope(droop_frac=0.0)
        wf *= 1.0 + self.rng.normal(0.0, 0.08, N_SAMPLES)  # counting noise
        nburst = self.rng.poisson(2.0)
        for _ in range(nburst):                     # stochastic micro-bursts
            i0 = self.rng.integers(0, N_SAMPLES - 8)
            wf[i0:i0 + 8] += wpm * self.rng.uniform(0.5, 2.0) * \
                np.exp(-np.arange(8) / 2.0)
        wf += np.abs(self.rng.normal(dark_wpm, dark_wpm, N_SAMPLES))
        return np.maximum(wf, 0.0).astype(np.float32)
