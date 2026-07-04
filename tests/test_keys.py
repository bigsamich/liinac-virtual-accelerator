"""Tests for pip2va.common.keys — Redis key/channel naming."""
from pip2va.common import keys


def test_stream_key():
    assert keys.stream("bpm.orbit") == "stream:bpm.orbit"


def test_settings_key():
    assert keys.settings("magnet", "MEBT:Q01") == "settings:magnet:MEBT:Q01"


def test_readback_key():
    assert keys.readback("rf", "HWR:CAV3") == "readback:rf:HWR:CAV3"


def test_truth_key():
    assert keys.truth("beam") == "truth:beam"


def test_fault_key():
    assert keys.fault("rf", "SSR1:CAV2") == "fault:rf:SSR1:CAV2"


def test_heartbeat_key():
    assert keys.heartbeat("timing") == "hb:timing"


def test_channels():
    assert keys.CH_TICK == "pulse.tick"
    assert keys.CH_SETTINGS == "settings.changed"
    assert keys.CH_MPS == "mps.trip"
    assert keys.CH_FAULT == "device.fault"
