"""Counter/hash-based deterministic RNG — the load-bearing piece of the
determinism substrate.

Randomness is a PURE FUNCTION of ``(global_seed, *keys)`` — typically
``(global_seed, pulse_id, entity, channel)`` — not a stateful stream. This is
the Philox/Random123 idea: the draw for a given ``(pulse, entity, channel)`` is
identical every run regardless of execution history, service restarts, or event
ordering.

Two properties fall out of this and drive the whole design:

* **Reproducibility** — a golden-master test can assert bit-exact readout
  streams, because pulse N's noise no longer depends on how many draws happened
  before it.
* **Common Random Numbers (CRN)** — forked what-if branches that share the same
  ``global_seed`` see *identical* noise, so differences between branches are
  pure signal from the setpoint delta, not RNG variance. This is what makes the
  branch/optimizer engine converge.

Contrast with the old model (one ``np.random.Generator`` per service, seeded
once and advanced every pulse): there the value at pulse N depended on the
total number of draws so far, so a restart or an extra pulse desynced every
downstream stream.
"""
from __future__ import annotations

import zlib

import numpy as np

from .config import settings as _settings


# Process-wide "active" master seed. Defaults to settings.global_seed, but a
# driver/branch can override it for its run (one seed per process/branch; CRN
# branches share it, different-universe runs set different values).
_ACTIVE_SEED: int | None = None


def set_active_seed(seed: int | None) -> None:
    global _ACTIVE_SEED
    _ACTIVE_SEED = None if seed is None else int(seed)


def active_seed() -> int:
    if _ACTIVE_SEED is not None:
        return _ACTIVE_SEED
    return _settings.global_seed


def _key(x) -> int:
    """Map any hashable key to a stable 32-bit int (crc32 for strings, so it is
    identical across processes/runs — unlike Python's salted ``hash``)."""
    if isinstance(x, (int, np.integer)):
        return int(x) & 0xFFFFFFFF
    return zlib.crc32(str(x).encode("utf-8")) & 0xFFFFFFFF


def pulse_rng(*keys, seed: int | None = None) -> np.random.Generator:
    """A fresh Generator that is a pure function of ``(seed, *keys)``.

    Pass a stable identity, e.g. ``pulse_rng(pulse_id, "BTL:BPM37", "noise")``.
    The same keys always return the same stream, in any process, any run.
    """
    base = active_seed() if seed is None else int(seed)
    ss = np.random.SeedSequence([base & 0xFFFFFFFF] + [_key(k) for k in keys])
    return np.random.default_rng(ss)


def normal(loc, scale, *keys, size=None, seed: int | None = None):
    """Convenience: a deterministic normal draw keyed on ``keys``."""
    return pulse_rng(*keys, seed=seed).normal(loc, scale, size)


def uniform(low, high, *keys, size=None, seed: int | None = None):
    return pulse_rng(*keys, seed=seed).uniform(low, high, size)
