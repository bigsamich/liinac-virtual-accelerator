"""Array backend selection: CuPy on the GPU when available, NumPy otherwise.

PIP2VA_BACKEND=numpy|cupy forces a choice; the default ("auto") tries CuPy.
"""
from __future__ import annotations

import os

import numpy as np


def get_xp(name: str | None = None):
    """Return the array module (cupy or numpy)."""
    name = name or os.environ.get("PIP2VA_BACKEND", "auto")
    if name == "numpy":
        return np
    try:
        import cupy as cp
        cp.zeros(1).sum()  # probe: raises if no usable device
        return cp
    except Exception:
        if name == "cupy":
            raise RuntimeError("PIP2VA_BACKEND=cupy but no usable CUDA device")
        return np


def asnumpy(arr):
    """Bring an array back to host memory regardless of backend."""
    return arr.get() if hasattr(arr, "get") else np.asarray(arr)
