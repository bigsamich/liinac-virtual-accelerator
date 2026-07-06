"""Self-describing data contracts.

Every service registers what it publishes (streams) and what it accepts
(settings) into redis meta keys. Consumers — the EPICS gateway first —
build their interfaces from this registry instead of hand-written maps.

  meta:stream:<product>   JSON {fields: {name: {unit, scale, label}},
                                index_key, pv}
  meta:settings:<cls>     JSON {fields: {name: {lo, hi, unit}},
                                devices_key | devices}
"""
from __future__ import annotations

import json


def register_stream(r, product: str, fields: dict, pv: str,
                    index_key: str | None = None):
    """Declare a stream product: its per-field metadata, the PV prefix it
    should appear under, and optionally a redis key holding the device
    index (name per array slot) for per-device scalar PVs."""
    r.set(f"meta:stream:{product}", json.dumps(
        {"fields": fields, "pv": pv, "index_key": index_key}))


def register_settings(r, cls: str, fields: dict,
                      devices: list[str] | None = None,
                      pv: str | None = None):
    """Declare a settings class: writable fields with limits, and the
    device names that accept them."""
    r.set(f"meta:settings:{cls}", json.dumps(
        {"fields": fields, "devices": devices or ["main"],
         "pv": pv or cls.upper()}))


def load_registry(r) -> tuple[dict, dict]:
    streams, settings = {}, {}
    for k in r.scan_iter("meta:stream:*"):
        streams[k.decode().split(":", 2)[2]] = json.loads(r.get(k))
    for k in r.scan_iter("meta:settings:*"):
        settings[k.decode().split(":", 2)[2]] = json.loads(r.get(k))
    return streams, settings
