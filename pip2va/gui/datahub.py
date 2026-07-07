"""DataHub: the single Redis gateway for the GUI.

A QThread follows every telemetry stream with XREAD and re-emits entries as
Qt signals; pages never touch Redis directly. Writes (setpoints, resets,
scan requests, fault injection) go through explicit methods here.
"""
from __future__ import annotations

import json
import threading

import redis
from PyQt6.QtCore import QThread, pyqtSignal

from pip2va.common import audit, codec, keys
from pip2va.common.config import Settings

STREAM_SIGNALS = {
    "bpm.orbit": "orbit",
    "blm.losses": "losses",
    "toroid.current": "toroids",
    "rf.cavity": "rf",
    "magnet.readback": "magnets",
    "wf.wcm": "wcm",
    "scraper.current": "scraper",
    "profile.allison": "allison",
    "beam.deep": "deep",
    "profile.scan": "scan",
    "wf.toroid": "wfToroid",
    "wf.capture": "wfCapture",
    "wf.rf": "wfRf",
}


class DataHub(QThread):
    orbit = pyqtSignal(int, object)
    losses = pyqtSignal(int, object)
    toroids = pyqtSignal(int, object)
    rf = pyqtSignal(int, object)
    magnets = pyqtSignal(int, object)
    wcm = pyqtSignal(int, object)
    scraper = pyqtSignal(int, object)
    allison = pyqtSignal(int, object)
    deep = pyqtSignal(int, object)
    scan = pyqtSignal(int, object)
    wfToroid = pyqtSignal(int, object)
    wfCapture = pyqtSignal(int, object)
    wfRf = pyqtSignal(int, object)
    mpsEvent = pyqtSignal(object)
    beamState = pyqtSignal(object)
    connected = pyqtSignal(bool)

    def __init__(self, redis_client=None, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings()
        self.r = redis_client if redis_client is not None else \
            redis.Redis.from_url(self.settings.redis_url)
        self._running = False
        self._ready = threading.Event()

    # ------------------------------------------------------------ stream loop

    def run(self):
        self._running = True
        names = [keys.stream(p) for p in STREAM_SIGNALS]
        names.append(keys.stream("mps.events"))
        streams: dict = {}
        for nm in names:
            try:
                last = self.r.xrevrange(nm, count=1)
                streams[nm] = last[0][0] if last else "0-0"
            except redis.RedisError:
                streams[nm] = "0-0"
        self._ready.set()   # start positions resolved; new entries will emit
        ok = None
        while self._running:
            try:
                resp = self.r.xread(streams, block=200, count=20)
                if ok is not True:
                    ok = True
                    self.connected.emit(True)
            except redis.RedisError:
                if ok is not False:
                    ok = False
                    self.connected.emit(False)
                self.msleep(500)
                continue
            for skey, entries in resp or []:
                skey = skey.decode() if isinstance(skey, bytes) else skey
                for eid, fields in entries:
                    streams[skey] = eid
                    self._dispatch(skey, fields)

    def _dispatch(self, skey: str, fields: dict):
        product = skey.split(":", 1)[1]
        if product == "mps.events":
            ev = {(k.decode() if isinstance(k, bytes) else k):
                  (v.decode() if isinstance(v, bytes) else v)
                  for k, v in fields.items()}
            self.mpsEvent.emit(ev)
            return
        sig = STREAM_SIGNALS.get(product)
        if sig is None or b"d" not in fields:
            return
        pulse_id, data = codec.unpack(fields[b"d"])
        getattr(self, sig).emit(pulse_id, data)
        if product == "bpm.orbit":
            self.beamState.emit(self._read_state())

    def _read_state(self) -> dict:
        try:
            raw = self.r.hgetall("state:beam")
            st = {k.decode(): float(v) for k, v in raw.items()}
            permit = self.r.get("state:mps.permit")
            st["permit"] = 0.0 if permit in (b"0", "0") else 1.0
            return st
        except (redis.RedisError, ValueError):
            return {}

    def wait_ready(self, timeout: float = 2.0) -> bool:
        """Block until the stream reader has resolved its start positions."""
        return self._ready.wait(timeout)

    def stop(self):
        self._running = False
        self.wait(2000)

    # ------------------------------------------------------------ commands

    def set_setting(self, cls: str, name: str, field: str, value):
        key = keys.settings(cls, name)
        self.r.hset(key, field, value)
        audit.log_setting(self.r, key, field, value, "gui")
        self.r.publish(keys.CH_SETTINGS, json.dumps({"key": key}))

    def settings_log(self, n: int = 100) -> list[dict]:
        return audit.read_log(self.r, n)

    def get_settings(self, cls: str, name: str) -> dict:
        raw = self.r.hgetall(keys.settings(cls, name))
        out = {}
        for k, v in raw.items():
            k = k.decode() if isinstance(k, bytes) else k
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v.decode() if isinstance(v, bytes) else v
        return out

    def get_readback(self, cls: str, name: str) -> dict:
        raw = self.r.hgetall(keys.readback(cls, name))
        out = {}
        for k, v in raw.items():
            k = k.decode() if isinstance(k, bytes) else k
            v = v.decode() if isinstance(v, bytes) else v
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v
        return out

    def history(self, product: str, n: int = 600) -> list[tuple[int, dict]]:
        out = []
        for _, fields in self.r.xrevrange(keys.stream(product), count=n):
            if b"d" in fields:
                out.append(codec.unpack(fields[b"d"]))
        out.reverse()
        return out

    def event_history(self, n: int = 100) -> list[dict]:
        out = []
        for _, fields in self.r.xrevrange(keys.stream("mps.events"), count=n):
            out.append({(k.decode() if isinstance(k, bytes) else k):
                        (v.decode() if isinstance(v, bytes) else v)
                        for k, v in fields.items()})
        return out

    def get_index(self, kind: str) -> list[str]:
        raw = self.r.get(f"lattice:{kind}.index")
        return json.loads(raw) if raw else []

    def request_wire_scan(self, name: str, plane: str = "x",
                          points: int = 64, ppp: int = 1):
        self.r.hset(f"req:wire:{name}", mapping={
            "plane": plane, "points": points, "ppp": ppp})

    def request_lw_scan(self, name: str, plane: str = "x",
                        points: int = 48, ppp: int = 1, halo: int = 0):
        self.r.hset(f"req:lw:{name}", mapping={
            "plane": plane, "points": points, "ppp": ppp, "halo": halo})

    def select_3d_station(self, name: str):
        """Choose the scanner station where the GPU tracker dumps a 3D cloud."""
        self.r.hset(keys.settings("wf3d", "main"), "station", name)

    def select_waveforms(self, names: list[str], rf_names: list[str] = ()):
        """Choose up to 8 devices for continuous intra-pulse capture."""
        self.r.hset(keys.settings("wfsel", "main"), mapping={
            "devices": ",".join(names[:8]),
            "rf": ",".join(list(rf_names)[:8])})

    def get_postmortem(self):
        blob = self.r.get("wf:postmortem")
        return codec.unpack(blob) if blob else None

    def mps_reset(self):
        self.r.hset(keys.settings("mps", "main"), "reset", 1)

    def get_state(self, name: str) -> dict:
        raw = self.r.hgetall(f"state:{name}")
        out = {}
        for k, v in raw.items():
            k = k.decode() if isinstance(k, bytes) else k
            v = v.decode() if isinstance(v, bytes) else v
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v
        return out

    def set_autotune(self, enable: bool):
        self.set_setting("autotune", "main", "enable", int(enable))

    def run_bba(self):
        """Start the beam-based alignment campaign (autotune service)."""
        self.set_setting("autotune", "main", "bba", 1)

    def rescue(self):
        """One-shot restore of the whole machine to design settings."""
        self.set_setting("autotune", "main", "restore", 1)

    def inject_fault(self, cls: str, name: str, ftype: str,
                     magnitude: float = 0.0, ttl_s: int = 0):
        key = keys.fault(cls, name)
        self.r.hset(key, mapping={"type": ftype, "magnitude": magnitude})
        if ttl_s > 0:
            self.r.expire(key, ttl_s)
        audit.log_setting(self.r, key, ftype, magnitude, "fault-injection")

    def active_faults(self) -> list[str]:
        return sorted(k.decode() if isinstance(k, bytes) else k
                      for k in self.r.scan_iter("fault:*"))

    def clear_fault(self, cls: str, name: str):
        self.r.delete(keys.fault(cls, name))
