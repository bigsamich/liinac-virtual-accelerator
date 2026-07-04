"""SCORE-style machine snapshots: save / compare / restore all setpoints.

A snapshot is a JSON file capturing every settings:* hash. Restore writes
the values back (through the audit log) and nudges every sim with a bulk
settings.changed, so readbacks slew realistically toward the recalled state.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import audit, keys

DEFAULT_DIR = Path.home() / ".pip2va" / "snapshots"

# hashes that are machine state, not operator setpoints
EXCLUDE_PREFIXES = ("settings:mps:", "settings:autotune:", "settings:wfsel:",
                    "settings:wf3d:")


def _dir(directory: str | Path | None) -> Path:
    d = Path(directory) if directory else DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def collect(r) -> dict[str, dict]:
    """All operator setpoint hashes as {key: {field: value}}."""
    out: dict[str, dict] = {}
    for k in r.scan_iter("settings:*"):
        key = k.decode() if isinstance(k, bytes) else k
        if any(key.startswith(p) for p in EXCLUDE_PREFIXES):
            continue
        h = {}
        for f, v in r.hgetall(key).items():
            f = f.decode() if isinstance(f, bytes) else f
            v = v.decode() if isinstance(v, bytes) else v
            if f == "reset":
                continue
            try:
                h[f] = float(v)
            except (TypeError, ValueError):
                h[f] = v
        if h:
            out[key] = h
    return out


def save(r, name: str, note: str = "", directory=None) -> Path:
    snap = {"name": name, "t": time.time(), "note": note,
            "settings": collect(r)}
    path = _dir(directory) / f"{name}.json"
    path.write_text(json.dumps(snap, indent=1, sort_keys=True))
    return path


def list_snapshots(directory=None) -> list[dict]:
    out = []
    for p in sorted(_dir(directory).glob("*.json")):
        try:
            s = json.loads(p.read_text())
            out.append({"name": s.get("name", p.stem), "t": s.get("t", 0),
                        "note": s.get("note", ""),
                        "n": len(s.get("settings", {})), "path": str(p)})
        except (ValueError, OSError):
            continue
    return out


def load(name: str, directory=None) -> dict:
    return json.loads((_dir(directory) / f"{name}.json").read_text())


def diff(r, snap: dict, tol: float = 1e-6) -> list[dict]:
    """Differences between the live machine and a snapshot."""
    live = collect(r)
    saved = snap["settings"]
    out = []
    for key in sorted(set(live) | set(saved)):
        lf, sf = live.get(key, {}), saved.get(key, {})
        for f in sorted(set(lf) | set(sf)):
            a, b = lf.get(f), sf.get(f)
            if isinstance(a, float) and isinstance(b, float):
                scale = max(abs(a), abs(b), 1.0)
                if abs(a - b) / scale <= tol:
                    continue
            elif a == b:
                continue
            out.append({"key": key, "field": f, "live": a, "saved": b})
    return out


def restore(r, snap: dict) -> int:
    """Write a snapshot's setpoints back to the machine."""
    n = 0
    pipe = r.pipeline(transaction=False)
    for key, fields in snap["settings"].items():
        for f, v in fields.items():
            pipe.hset(key, f, v)
            audit.log_setting(r, key, f, v,
                              f"restore:{snap.get('name', '?')}")
            n += 1
    pipe.execute()
    r.publish(keys.CH_SETTINGS, json.dumps({"key": "bulk:restore"}))
    return n
