"""EPICS PVAccess gateway — a thin p4p SharedPV server, NOT an IOC.

Fully registry-driven: services self-describe their streams and settings
(pip2va.common.schema -> meta:stream:* / meta:settings:*), and this
gateway builds its PV set from that registry at startup. Add a new stream
anywhere with schema.register_stream() and it appears on PVA — no gateway
changes.

PV shapes generated per registry entry:
  streams:  <PV>:<FIELD>            full array (NTScalar 'ad')
            <PV>:<SEC>:<DEV>:<FIELD>_RB  per-device scalar (via index_key)
  settings: <PV>:<SEC>:<DEV>:<FIELD>_SP  writable, limit-clamped, audited
  always:   PIP2:BEAM:W/T/IOUT/PULSE, PIP2:MPS:PERMIT, PIP2:MPS:RESET

Run: python -m pip2va.services.epics_gateway.main (host networking for
PVA discovery; compose service `epics-gateway`).
"""
from __future__ import annotations

import json
import logging
import os
import time

import numpy as np
import redis as redis_lib

from pip2va.common import audit, codec, keys, naming, schema
from pip2va.common.config import Settings

log = logging.getLogger("epics-gateway")

try:
    from p4p.nt import NTScalar
    from p4p.server import Server
    from p4p.server.thread import SharedPV
    HAVE_P4P = True
except ImportError:                       # pragma: no cover
    HAVE_P4P = False

STATE_PVS = {"PIP2:BEAM:W": "w_out", "PIP2:BEAM:T": "transmission",
             "PIP2:BEAM:IOUT": "i_out_ma", "PIP2:BEAM:PULSE": "pulse_id"}


def _dev_pv(prefix: str, device: str, field: str, suffix: str) -> str:
    sec, _, nm = device.partition(":")
    f = field.upper().replace("CURRENT", "CUR").replace("_MA", "")
    return f"{prefix}:{sec}:{nm}:{f}_{suffix}" if nm else \
        f"{prefix}:{f}_{suffix}"


def build_pv_plan(streams: dict, settings: dict) -> dict:
    """PV name -> binding descriptor. Pure + testable without p4p."""
    plan: dict[str, dict] = {}
    for name, fld in STATE_PVS.items():
        plan[name] = {"kind": "state", "field": fld}
    plan["PIP2:MPS:PERMIT"] = {"kind": "permit"}
    plan["PIP2:MPS:RESET"] = {"kind": "write",
                              "target": ("mps", "main", "reset"),
                              "lo": 0, "hi": 1}
    for product, m in streams.items():
        for fld, meta in m["fields"].items():
            plan[f"{m['pv']}:{fld.upper()}"] = {
                "kind": "array", "product": product, "field": fld,
                "scale": meta.get("scale", 1.0)}
        if m.get("index_key"):
            plan[f"__index__:{product}"] = {
                "kind": "index", "index_key": m["index_key"],
                "pv": m["pv"], "product": product,
                "fields": {f: mm.get("scale", 1.0)
                           for f, mm in m["fields"].items()}}
    for cls, m in settings.items():
        grp = {"rf": "LLRF", "magnet": "MAG"}.get(cls, "INST")
        for dev in m["devices"]:
            for fld, lim in m["fields"].items():
                nm = _dev_pv(m["pv"], dev if dev != "main" else "",
                             fld, "SP")
                if NAMER is not None and dev in NAMER.map:
                    nm = NAMER.pv(dev, grp, fld, setting=True)
                plan[nm] = {"kind": "write", "target": (cls, dev, fld),
                            "lo": lim.get("lo"), "hi": lim.get("hi")}
    return plan


NAMER = None


class Gateway:
    def __init__(self, r=None, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.r = r or redis_lib.Redis.from_url(self.settings.redis_url)
        self.hz = float(os.environ.get("PIP2VA_EPICS_HZ", "10"))
        from pip2va.common.lattice import load_lattice
        global NAMER
        self.namer = naming.store_map(self.r, load_lattice())
        NAMER = self.namer
        streams, setts = schema.load_registry(self.r)
        if not streams:
            log.warning("registry empty — services not started yet? "
                        "will retry")
        self.plan = build_pv_plan(streams, setts)
        # expand per-device scalar RBs from index entries
        self.dev_rb: dict[str, tuple] = {}   # pv -> (product, field, j, scale)
        for name in [n for n in self.plan if n.startswith("__index__:")]:
            d = self.plan.pop(name)
            raw = self.r.get(d["index_key"])
            if not raw:
                continue
            for j, devfld in enumerate(json.loads(raw)):
                dev, _, fld_hint = devfld.partition(":")
                for fld, scale in d["fields"].items():
                    # magnet index entries are DEVICE:FIELD; instrument
                    # indexes are plain device names
                    if ":" in devfld and devfld.count(":") == 2:
                        dev_name, fld_name = devfld.rsplit(":", 1)
                        if fld_name != fld and fld == "values":
                            fld_name = fld_name  # magnet: value slot
                        pv = (self.namer.pv(dev_name, "MAG", fld_name)
                              if dev_name in self.namer.map else
                              _dev_pv(d["pv"], dev_name, fld_name, "RB"))
                        self.dev_rb[pv] = (d["product"], fld, j, scale)
                        break
                    grp = {"PIP2:RF": "LLRF"}.get(d["pv"], "INST")
                    pv = (self.namer.pv(devfld, grp, fld)
                          if devfld in self.namer.map else
                          _dev_pv(d["pv"], devfld, fld, "RB"))
                    self.dev_rb[pv] = (d["product"], fld, j, scale)
        self.pvs: dict[str, SharedPV] = {}
        for name, d in self.plan.items():
            array = d["kind"] == "array"
            pv = SharedPV(nt=NTScalar("ad" if array else "d"),
                          initial=[0.0] if array else 0.0)
            if d["kind"] == "write":
                pv.put(self._make_put(d))
            self.pvs[name] = pv
        for name in self.dev_rb:
            self.pvs[name] = SharedPV(nt=NTScalar("d"), initial=0.0)
        log.info("PVA registry: %d PVs (%d writable, %d per-device RB)",
                 len(self.pvs),
                 sum(1 for d in self.plan.values() if d["kind"] == "write"),
                 len(self.dev_rb))

    def _make_put(self, d):
        cls, dev, fld = d["target"]

        def handler(pv, op):
            val = float(op.value())
            if d.get("lo") is not None:
                val = min(max(val, d["lo"]), d["hi"])
            key = keys.settings(cls, dev)
            self.r.hset(key, fld, val)
            audit.log_setting(self.r, key, fld, val, "epics")
            self.r.publish(keys.CH_SETTINGS, json.dumps({"key": key}))
            pv.post(val)
            op.done()
        return handler

    def _latest(self, product):
        e = self.r.xrevrange(keys.stream(product), count=1)
        if not e:
            return None
        _, d = codec.unpack(e[0][1][b"d"])
        return d

    def refresh(self):
        st = {k.decode(): v.decode()
              for k, v in self.r.hgetall("state:beam").items()}
        latest: dict = {}
        for name, d in self.plan.items():
            try:
                if d["kind"] == "state" and st:
                    self.pvs[name].post(float(st.get(d["field"], 0.0)))
                elif d["kind"] == "permit":
                    self.pvs[name].post(
                        1.0 if self.r.get("state:mps.permit") == b"1"
                        else 0.0)
                elif d["kind"] == "array":
                    if d["product"] not in latest:
                        latest[d["product"]] = self._latest(d["product"])
                    data = latest[d["product"]]
                    if data is not None and d["field"] in data:
                        self.pvs[name].post(
                            np.asarray(data[d["field"]], dtype=float)
                            * d["scale"])
            except Exception:
                continue
        for name, (product, fld, j, scale) in self.dev_rb.items():
            try:
                data = latest.get(product) or self._latest(product)
                latest[product] = data
                if data is not None and j < len(data[fld]):
                    self.pvs[name].post(float(data[fld][j]) * scale)
            except Exception:
                continue

    def run(self):
        with Server(providers=[self.pvs]):
            log.info("PVA server up at %.0f Hz", self.hz)
            period = 1.0 / self.hz
            while True:
                t0 = time.monotonic()
                self.refresh()
                time.sleep(max(0.0, period - (time.monotonic() - t0)))


def main():
    logging.basicConfig(level=logging.INFO)
    if not HAVE_P4P:
        raise SystemExit("p4p not installed: pip install p4p")
    # wait for the registry (services register on startup)
    gw = Gateway()
    while len(gw.plan) < 10:
        log.info("waiting for service registry...")
        time.sleep(5)
        gw = Gateway()
    gw.run()


if __name__ == "__main__":
    main()
