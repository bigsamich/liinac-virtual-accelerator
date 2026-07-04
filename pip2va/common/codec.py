"""msgpack payload codec for stream entries and truth hashes.

Wire format: msgpack map {"pulse_id": int, "data": {name: value}} where array
values are encoded as {"__nd__": True, "shape": [...], "buf": <float32 bytes>}
and scalars/strings pass through untouched.
"""
from __future__ import annotations

import msgpack
import numpy as np


def _encode_value(v):
    if isinstance(v, np.ndarray):
        arr = np.ascontiguousarray(v, dtype=np.float32)
        return {"__nd__": True, "shape": list(arr.shape), "buf": arr.tobytes()}
    if isinstance(v, (list, tuple)):
        return _encode_value(np.asarray(v, dtype=np.float32))
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    return v


def _decode_value(v):
    if isinstance(v, dict) and v.get("__nd__"):
        return np.frombuffer(v["buf"], dtype=np.float32).reshape(v["shape"])
    return v


def pack(pulse_id: int, data: dict) -> bytes:
    payload = {"pulse_id": int(pulse_id),
               "data": {k: _encode_value(v) for k, v in data.items()}}
    return msgpack.packb(payload, use_bin_type=True)


def unpack(blob: bytes) -> tuple[int, dict]:
    payload = msgpack.unpackb(blob, raw=False)
    data = {k: _decode_value(v) for k, v in payload["data"].items()}
    return payload["pulse_id"], data
