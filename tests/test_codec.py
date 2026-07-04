"""Tests for pip2va.common.codec — msgpack array payload encoding."""
import numpy as np
import pytest

from pip2va.common import codec


def test_roundtrip_ndarray():
    data = {"x": np.array([1.0, 2.5, -3.25], dtype=np.float64)}
    blob = codec.pack(42, data)
    assert isinstance(blob, bytes)
    pulse_id, out = codec.unpack(blob)
    assert pulse_id == 42
    assert out["x"].dtype == np.float32
    np.testing.assert_allclose(out["x"], [1.0, 2.5, -3.25], rtol=1e-6)


def test_roundtrip_list():
    blob = codec.pack(7, {"vals": [0.5, 1.5]})
    pulse_id, out = codec.unpack(blob)
    assert pulse_id == 7
    assert isinstance(out["vals"], np.ndarray)
    np.testing.assert_allclose(out["vals"], [0.5, 1.5])


def test_roundtrip_2d():
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    pulse_id, out = codec.unpack(codec.pack(1, {"m": arr}))
    assert out["m"].shape == (3, 4)
    np.testing.assert_array_equal(out["m"], arr)


def test_scalar_passthrough():
    """Non-array scalars (floats/ints/strings) survive the round trip."""
    pulse_id, out = codec.unpack(codec.pack(3, {"W": 802.5, "n": 5, "tag": "ok"}))
    assert out["W"] == pytest.approx(802.5)
    assert out["n"] == 5
    assert out["tag"] == "ok"


def test_empty_array():
    pulse_id, out = codec.unpack(codec.pack(0, {"e": np.array([], dtype=np.float32)}))
    assert out["e"].size == 0
