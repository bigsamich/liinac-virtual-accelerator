"""ED0011740 Rev B — PIP-II official naming convention.

Component:  Complex:System:Device:ID#
EPICS PV:   Complex:System_Group_DeviceID#:Signal
            (settings signals carry a lowercase 's' prefix)

Complexes: LWFE (IS/LEBT/RFQ/MEBT), LSCL (cryomodules + warm units),
LBTL (1st BTL dipole up to first ORBUMP, incl septum), LBAL (absorber
line), BSTR (ORBUMP + downstream injection), LACC (global systems).

Identifier numbering (Table 1/2): 01XX IS/LEBT, 02XX RFQ, 03XX MEBT,
1XXX HWR (CM 1100, cav 1101-1108), 2XXX SSR1 (2100/2200, 8 cav each),
3XXX SSR2 (3100..3700, 5 cav each), 4XXX LB650 (4100..4900, 4 cav),
5XXX HB650 (5100..5600, 6 cav), 7XXX straight-ahead line, 8XXX BTL/BAL
(ARC1 80##, straight 81-83##, ARC2 84##, injection 85##, BAL 86##).
SCL devices are identified by their NEAREST CAVITY; MEBT increments per
doublet/triplet; IS/LEBT per solenoid; BTL per quadrupole.

The same official name is used as the redis channel/key alias
(meta:official maps sim element name -> official component name).
"""
from __future__ import annotations

import json

DEVICE_CODE = {
    "rfgap": "CAV", "rfq": "RFQ", "solenoid": "SOL", "quad": "Q",
    "skew_quad": "SQ", "corrector": "CORR", "dipole": "DIP",
    "bpm": "BPM", "blm": "BLM", "toroid": "ACCT", "wire_scanner": "WS",
    "chopper": "CHOP", "source": "ISRC", "aperture": "COLL",
    "valve": "GV", "halo": "HALO", "bsm": "BSM", "septum": "SEPT",
    "orbump": "ORB", "foil": "FOIL", "sweep": "SWM",
    "scraper2": "SCRP", "allison": "ASCN", "ffc": "FFC", "eid": "EID",
    "absorber": "ABS", "dpi": "DPI", "rfsep": "RFSEP", "mwpm": "MWPM",
}
# signal codes (sim field -> official-style signal)
SIGNAL = {"amp": "AMPL", "phase": "PHS", "detuning_hz": "DET",
          "forward_pw": "FWDPWR", "ff": "FF", "current": "I",
          "current_x": "IX", "current_y": "IY",
          "current_ma": "CURRENT",
          "duty": "DUTY", "x": "XPOS", "y": "YPOS", "wpm": "LOSS",
          "i_ma": "CURRENT", "w_tof": "WTOF", "sum": "SUM", "notch": "NOTCH",
          "turn": "TURN"}

_CAV_PER_CM = {"HWR": 8, "SSR1": 8, "SSR2": 5, "LB650": 4, "HB650": 6}
_SEC_BASE = {"HWR": 1000, "SSR1": 2000, "SSR2": 3000,
             "LB650": 4000, "HB650": 5000}
_SYS_ABBR = {"LB650": "LB", "HB650": "HB"}


def _cavity_ident(section: str, k: int) -> int:
    """k = 1-based cavity number within the section -> official ID#."""
    per = _CAV_PER_CM[section]
    cm = (k - 1) // per + 1
    slot = (k - 1) % per + 1
    return _SEC_BASE[section] + cm * 100 + slot


def _system(section: str, ident: int) -> str:
    if section in _SEC_BASE:
        cm = (ident % 1000) // 100
        return f"{_SYS_ABBR.get(section, section)}-{cm}"
    return section


class Namer:
    """Computes official names for every element of the sim lattice."""

    def __init__(self, lat):
        self.lat = lat
        self.map: dict[str, dict] = {}
        # per-section cavity positions for nearest-cavity identification
        cav_s: dict[str, list] = {}
        counts: dict[str, int] = {}
        for e in lat.elements:
            if e.type == "rfgap" and e.section in _CAV_PER_CM:
                k = counts.get(e.section, 0) + 1
                counts[e.section] = k
                cav_s.setdefault(e.section, []).append(
                    (e.s, _cavity_ident(e.section, k), e.name))
        mebt_cell = 0
        lebt_sol = 0
        btl_q = 0
        for e in lat.elements:
            if e.type == "drift":
                continue
            sec, dev = e.section, DEVICE_CODE.get(e.type)
            if dev is None:
                continue
            if sec in _CAV_PER_CM:
                cavs = cav_s.get(sec, [])
                if e.type == "rfgap":
                    ident = next(i for s, i, nm in cavs if nm == e.name)
                else:
                    ident = min(cavs, key=lambda c: abs(c[0] - e.s))[1] \
                        if cavs else _SEC_BASE[sec]
                comp = "LSCL"
                system = _system(sec, ident)
            elif sec == "LEBT":
                if e.type == "solenoid":
                    lebt_sol += 1
                ident = 100 + lebt_sol * 10 + 1
                comp, system = "LWFE", "LEBT"
            elif sec == "RFQ":
                ident, comp, system = 201, "LWFE", "RFQ"
            elif sec == "MEBT":
                if e.type == "quad" and self._is_cell_start(e):
                    mebt_cell += 1
                ident = 300 + max(mebt_cell, 1) * 10 + 1
                comp, system = "LWFE", "MEBT"
            elif sec == "BTL":
                if e.type == "quad":
                    btl_q += 1
                # 70xx straight-ahead until first dipole region handled by
                # quad counter mapping onto the 8xxx lines
                ident = 8000 + btl_q
                comp, system = "LBTL", "BTL"
                if e.type in ("orbump", "foil"):
                    comp, ident = "BSTR", 8510 if e.type == "orbump" else 8500
                elif e.type == "sweep":
                    comp, ident = "LBAL", 8601 + btl_q % 10
            else:
                ident, comp, system = 0, "LACC", sec
            self.map[e.name] = {
                "component": f"{comp}:{system}:{dev}:{ident:04d}",
                "pv_base": f"{comp}:{system}", "device": dev,
                "ident": f"{ident:04d}"}
        self._quad_letter()

    def _is_cell_start(self, e) -> bool:
        # first quad of each MEBT doublet/triplet package
        prev = getattr(self, "_prev_mebt_q_s", -10.0)
        self._prev_mebt_q_s = e.s
        return (e.s - prev) > 0.5

    def _quad_letter(self):
        # A/B/C suffix for quads sharing an identifier (magnet packages)
        from collections import defaultdict
        groups = defaultdict(list)
        for nm, d in self.map.items():
            if d["device"] in ("Q", "SOL"):
                groups[d["component"]].append(nm)
        for comp, names in groups.items():
            if len(names) > 1:
                for j, nm in enumerate(names):
                    suffix = chr(ord("A") + j)
                    d = self.map[nm]
                    d["ident"] += suffix
                    d["component"] = comp + suffix

    def pv(self, el_name: str, group: str, signal: str,
           setting: bool = False) -> str:
        d = self.map[el_name]
        sig = SIGNAL.get(signal, signal.upper())
        if setting:
            sig = "s" + sig
        return f"{d['pv_base']}_{group}_{d['device']}{d['ident']}:{sig}"


def channel(namer: "Namer", el_name: str, signal: str) -> str:
    """Colon-form alias for redis channels, mirroring the official name:
    e.g. LSCL:HWR-1:ACCT:1100:CURRENT"""
    d = namer.map[el_name]
    return f"{d['component']}:{SIGNAL.get(signal, signal.upper())}"


def store_map(r, lat):
    """Publish the official-name registry (sim name <-> official) so any
    consumer — EPICS gateway, redis clients, GUIs — shares one namespace."""
    n = Namer(lat)
    r.set("meta:official", json.dumps(
        {k: v["component"] for k, v in n.map.items()}))
    return n
