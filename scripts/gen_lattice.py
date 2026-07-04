#!/usr/bin/env python3
"""Generate pip2va/lattice/pip2_lattice.yaml — the PIP-II machine definition.

Numbers follow the current PIP-II baseline (23 cryomodules / 119 SRF cavities;
LB650 = 9 CM x 4 cav) as compiled from the RDR/CDR/FDR and 2023-25 JACoW/arXiv
papers — see docs/research/pip2_machine_report.md. Operating cavity voltages
are derived from section energy checkpoints (2.1 / 10.3 / 35 / 185 / 516 /
800 MeV delivered); published V_eff capabilities set the quench limits.
Focusing strengths are analytic initial guesses (~75 deg phase advance per
period, thin-lens); the envelope engine treats them as design optics.

Run:  python scripts/gen_lattice.py   (rewrites the YAML in place)
"""
from __future__ import annotations

import math
from pathlib import Path

import yaml

M_HMINUS = 939.294  # MeV — H- rest mass (proton + 2 electrons)
C_MM = 299.792458   # p[MeV/c] / C_MM = Brho[T*m]

OUT = Path(__file__).resolve().parents[1] / "pip2va" / "lattice" / "pip2_lattice.yaml"

# Cavity family data (SRF2021 Table 2 + LLRF paper arXiv:2311.00900 Table 1)
# v_max_mv = published V_eff capability at beta_opt; ql, half_bw_hz for rf-sim.
CAV_FAMILY = {
    "buncher": {"v_max_mv": 0.09, "ql": 1.0e4, "half_bw_hz": 8100.0},
    "HWR":     {"v_max_mv": 2.0,  "ql": 2.32e6, "half_bw_hz": 35.0},
    "SSR1":    {"v_max_mv": 2.05, "ql": 3.02e6, "half_bw_hz": 53.8},
    "SSR2":    {"v_max_mv": 5.0,  "ql": 5.05e6, "half_bw_hz": 32.2},
    "LB650":   {"v_max_mv": 11.9, "ql": 1.036e7, "half_bw_hz": 31.4},
    "HB650":   {"v_max_mv": 19.9, "ql": 9.92e6, "half_bw_hz": 32.8},
    "debuncher": {"v_max_mv": 1.5, "ql": 2.0e4, "half_bw_hz": 5000.0},
}

# ---------------------------------------------------------------- helpers


def brho(w_mev: float) -> float:
    p = math.sqrt(w_mev**2 + 2.0 * w_mev * M_HMINUS)
    return p / C_MM


def sol_field(w_mev: float, period_m: float, sol_len: float, mu_deg: float = 75.0) -> float:
    """Solenoid B [T] for ~mu deg phase advance per all-focusing period.

    Thin lens: cos(mu) = 1 - Lp/(2 f);  1/f = (B / 2 Brho)^2 * Ls.
    """
    f = period_m / (2.0 * (1.0 - math.cos(math.radians(mu_deg))))
    return 2.0 * brho(w_mev) * math.sqrt(1.0 / (f * sol_len))


def doublet_grad(w_mev: float, period_m: float, quad_len: float, spacing: float) -> float:
    """Quad gradient [T/m] for a +/- doublet giving net ~75 deg/period focusing."""
    f_net = period_m / (2.0 * (1.0 - math.cos(math.radians(75.0))))
    f1 = math.sqrt(f_net * spacing)
    return brho(w_mev) / (f1 * quad_len)


class Builder:
    def __init__(self):
        self.elements: list[dict] = []
        self.sections: list[dict] = []
        self.s = 0.0
        self.w = 0.030  # MeV, source output
        self._sec = None
        self._counters: dict[str, int] = {}

    # -- section bookkeeping
    def begin(self, name: str, freq: float | None = None):
        self._sec = {"name": name, "s_start": round(self.s, 4), "w_in": round(self.w, 4),
                     "freq_mhz": freq}
        self._counters = {}

    def end(self):
        self._sec.update(s_end=round(self.s, 4), w_out=round(self.w, 4))
        self.sections.append(self._sec)

    def _n(self, tag: str) -> int:
        self._counters[tag] = self._counters.get(tag, 0) + 1
        return self._counters[tag]

    # -- element emitters
    def add(self, typ: str, name: str, length: float = 0.0, aperture: float = 0.02,
            params: dict | None = None, knobs: dict | None = None):
        self.elements.append({
            "name": name, "type": typ, "s": round(self.s, 4),
            "length": round(length, 4), "section": self._sec["name"],
            "aperture_radius": aperture,
            "params": params or {}, "knobs": knobs or {},
        })
        self.s += length

    def drift(self, length: float, aperture: float = 0.02):
        sec = self._sec["name"]
        self.add("drift", f"{sec}:D{self._n('D')}", length, aperture)

    def solenoid(self, length: float, b_t: float, aperture: float):
        sec = self._sec["name"]
        name = f"{sec}:SOL{self._n('SOL')}"
        i_design = round(b_t / 0.01, 3)  # 0.01 T/A calibration
        self.add("solenoid", name, length, aperture,
                 params={"field_per_amp": 0.01, "design_current": i_design,
                         "design_b": round(b_t, 5)},
                 knobs={"current": f"settings:magnet:{name}"})

    def quad(self, length: float, grad_tpm: float, aperture: float):
        sec = self._sec["name"]
        name = f"{sec}:Q{self._n('Q')}"
        i_design = round(grad_tpm / 0.1, 3)  # 0.1 (T/m)/A
        self.add("quad", name, length, aperture,
                 params={"grad_per_amp": 0.1, "design_current": i_design,
                         "design_grad": round(grad_tpm, 4)},
                 knobs={"current": f"settings:magnet:{name}"})

    def corrector(self, aperture: float):
        sec = self._sec["name"]
        name = f"{sec}:C{self._n('C')}"
        # SC-solenoid corrector windings: 2.5 mT*m; warm trims similar scale
        self.add("corrector", name, 0.05, aperture,
                 params={"bl_per_amp": 0.00025, "max_amp": 10.0},  # T*m/A
                 knobs={"current_x": f"settings:magnet:{name}",
                        "current_y": f"settings:magnet:{name}"})

    def bpm(self, aperture: float):
        sec = self._sec["name"]
        self.add("bpm", f"{sec}:BPM{self._n('BPM')}", 0.0, aperture,
                 params={"noise_um": 10.0, "phase_noise_deg": 0.3,
                         "intensity_noise_frac": 0.01})

    def blm(self):
        sec = self._sec["name"]
        self.add("blm", f"{sec}:BLM{self._n('BLM')}", 0.0, 1.0,
                 params={"noise_frac": 0.05, "dark_wpm": 0.001})

    def toroid(self, aperture: float):
        sec = self._sec["name"]
        self.add("toroid", f"{sec}:TOR{self._n('TOR')}", 0.05, aperture,
                 params={"noise_frac": 0.002, "floor_ma": 0.005})

    def wire(self, aperture: float, kind: str = "wire"):
        sec = self._sec["name"]
        self.add("wire_scanner", f"{sec}:WS{self._n('WS')}", 0.05, aperture,
                 params={"kind": kind, "bins": 64})

    def scraper(self, aperture: float):
        sec = self._sec["name"]
        self.add("aperture", f"{sec}:SCR{self._n('SCR')}", 0.1, aperture,
                 params={"kind": "scraper"})

    def cavity(self, length: float, v_mv: float, phi_deg: float, freq: float,
               aperture: float, family: str):
        sec = self._sec["name"]
        name = f"{sec}:CAV{self._n('CAV')}"
        fam = CAV_FAMILY[family]
        self.add("rfgap", name, length, aperture,
                 params={"v_mv": round(v_mv, 4), "phi_deg": phi_deg,
                         "freq_mhz": freq, "family": family,
                         "v_max_mv": fam["v_max_mv"],
                         "quench_mv": round(1.05 * fam["v_max_mv"], 4),
                         "ql": fam["ql"], "half_bw_hz": fam["half_bw_hz"]},
                 knobs={"amp": f"settings:rf:{name}", "phase": f"settings:rf:{name}"})
        self.w += v_mv * math.cos(math.radians(phi_deg))


# ---------------------------------------------------------------- machine


def build() -> dict:
    b = Builder()

    # ---- LEBT: 30 keV, 3 solenoids (0.62 T pk class), electrostatic chopper
    ap = 0.02
    b.begin("LEBT")
    b.add("source", "LEBT:SRC", 0.10, ap,
          params={"design_current_ma": 5.0, "max_current_ma": 15.0,
                  "energy_kev": 30.0},
          knobs={"current_ma": "settings:source:main"})
    b.drift(0.20, ap)
    b.solenoid(0.25, sol_field(b.w, 0.70, 0.25), ap)
    b.drift(0.20, ap)
    b.solenoid(0.25, sol_field(b.w, 0.70, 0.25), ap)
    b.drift(0.15, ap)
    b.add("chopper", "LEBT:CHOP", 0.16, 0.016,
          params={"kind": "lebt", "blocking_kv": 5.0},
          knobs={"duty": "settings:chopper:main"})
    b.drift(0.15, ap)
    b.solenoid(0.25, sol_field(b.w, 0.70, 0.25), ap)
    b.drift(0.10, ap)
    b.toroid(ap)
    b.end()

    # ---- RFQ: 4.45 m, 162.5 MHz 4-vane, 60 kV vanes, -> 2.1 MeV, T ~ 0.98
    b.begin("RFQ", 162.5)
    b.add("rfq", "RFQ:RFQ", 4.45, 0.004,
          params={"w_out_mev": 2.1, "freq_mhz": 162.5, "transmission": 0.98,
                  "vane_kv": 60.0, "v_design": 1.0,
                  "ql": 1.5e4, "half_bw_hz": 5500.0},
          knobs={"amp": "settings:rf:RFQ:RFQ", "phase": "settings:rf:RFQ:RFQ"})
    b.w = 2.1
    b.end()

    # ---- MEBT: 25 quads (2 doublets + 7 triplets), 3 bunchers (70 kV,
    # -90 deg), 2 TW chopper kickers + TZM absorber, 4 scraper sets, 12 BPMs
    ap = 0.014
    b.begin("MEBT", 162.5)
    b.toroid(ap)
    gq = 2.8  # T/m initial guess

    def doublet():
        b.quad(0.10, gq, ap); b.drift(0.12, ap); b.quad(0.10, -gq, ap)

    def triplet():
        b.quad(0.10, gq, ap); b.drift(0.12, ap)
        b.quad(0.10, -gq * 1.35, ap); b.drift(0.12, ap)
        b.quad(0.10, gq, ap)

    def pkg():
        b.corrector(ap); b.bpm(ap)

    def buncher():
        b.cavity(0.30, 0.07, -90.0, 162.5, ap, "buncher")

    b.drift(0.15, ap); doublet(); b.drift(0.12, ap); pkg()          # G1
    buncher(); b.drift(0.12, ap); triplet(); b.drift(0.12, ap); pkg()  # G2
    b.add("chopper", "MEBT:CHOP1", 0.50, 0.008,
          params={"kind": "mebt", "kicker": "helical-200ohm"},
          knobs={"duty": "settings:chopper:main"})
    b.drift(0.10, ap); b.bpm(ap)                                    # chopper-region BPM
    triplet(); b.drift(0.12, ap); pkg()                             # G3
    b.add("chopper", "MEBT:CHOP2", 0.50, 0.008,
          params={"kind": "mebt", "kicker": "helical-200ohm"},
          knobs={"duty": "settings:chopper:main"})
    b.drift(0.10, ap); b.bpm(ap)                                    # chopper-region BPM
    b.add("aperture", "MEBT:ABS", 0.25, 0.008,
          params={"kind": "absorber", "rating_kw": 21.0})
    b.blm()   # absorber-region loss monitor
    b.drift(0.10, ap)
    triplet(); b.drift(0.12, ap); pkg()                             # G4
    b.scraper(0.010)
    buncher(); b.drift(0.12, ap); triplet(); b.drift(0.12, ap); pkg()  # G5
    b.wire(ap)
    triplet(); b.drift(0.12, ap); pkg()                             # G6
    b.scraper(0.010)
    buncher(); b.drift(0.12, ap); triplet(); b.drift(0.12, ap); pkg()  # G7
    b.wire(ap)
    triplet(); b.drift(0.12, ap); pkg()                             # G8
    b.scraper(0.010)
    doublet(); b.drift(0.12, ap); pkg()                             # G9
    b.scraper(0.010)
    b.bpm(ap)                                                       # 12th BPM
    b.toroid(ap)
    b.end()

    # ---- HWR: 1 CM, 8 cav @162.5 (beta_opt 0.112) + 8 SC solenoids, s-c
    # period; 2.1 -> 10.3 MeV; phis -30 deg at SC entrance
    ap = 0.0165  # 33 mm cavity bore
    b.begin("HWR", 162.5)
    n_cav, phi = 8, -30.0
    v = (10.3 - 2.1) / (n_cav * math.cos(math.radians(phi)))
    for i in range(n_cav):
        b.drift(0.15, ap)
        b.cavity(0.25, v, phi, 162.5, ap, "HWR")
        b.drift(0.10, ap)
        b.solenoid(0.30, sol_field(b.w, 0.95, 0.30), ap)
        b.corrector(ap); b.bpm(ap)
        if i % 2 == 1:
            b.blm()
        b.drift(0.10, ap)
    b.toroid(ap)
    b.wire(ap, kind="laserwire")   # HWR-exit laserwire station
    b.end()

    # ---- SSR1: 2 CM x (8 cav @325, beta_opt 0.222 + 4 solenoids, c-s-c x4);
    # 10.3 -> 35 MeV
    ap = 0.015  # 30 mm bore
    b.begin("SSR1", 325.0)
    n_cav, phi = 16, -26.0
    v = (35.0 - 10.3) / (n_cav * math.cos(math.radians(phi)))
    for cm in range(2):
        b.drift(0.20, ap)
        for grp in range(4):
            b.cavity(0.30, v, phi, 325.0, ap, "SSR1")
            b.drift(0.10, ap)
            b.cavity(0.30, v, phi, 325.0, ap, "SSR1")
            b.drift(0.10, ap)
            b.solenoid(0.35, sol_field(b.w, 1.30, 0.35), ap)
            b.corrector(ap); b.bpm(ap)
            if grp % 2 == 1:
                b.blm()
            b.drift(0.10, ap)
        b.drift(0.20, ap)
    b.toroid(ap)
    b.wire(ap, kind="laserwire")   # SSR1-CM1-class laserwire station
    b.end()

    # ---- SSR2: 7 CM x (5 cav @325, beta_opt 0.47 + 3 sol; s-cc-s-cc-s-c);
    # 35 -> 185 MeV; 21 solenoids, 21 BPMs
    ap = 0.02  # 40 mm bore
    b.begin("SSR2", 325.0)
    n_cav, phi = 35, -23.0
    v = (185.0 - 35.0) / (n_cav * math.cos(math.radians(phi)))
    for cm in range(7):
        b.drift(0.20, ap)
        b.solenoid(0.40, sol_field(b.w, 2.10, 0.40), ap)
        b.corrector(ap); b.bpm(ap)
        b.cavity(0.40, v, phi, 325.0, ap, "SSR2"); b.drift(0.12, ap)
        b.cavity(0.40, v, phi, 325.0, ap, "SSR2"); b.drift(0.12, ap)
        b.solenoid(0.40, sol_field(b.w, 2.10, 0.40), ap)
        b.corrector(ap); b.bpm(ap)
        b.blm()
        b.cavity(0.40, v, phi, 325.0, ap, "SSR2"); b.drift(0.12, ap)
        b.cavity(0.40, v, phi, 325.0, ap, "SSR2"); b.drift(0.12, ap)
        b.solenoid(0.40, sol_field(b.w, 2.10, 0.40), ap)
        b.corrector(ap); b.bpm(ap)
        b.blm()
        b.cavity(0.40, v, phi, 325.0, ap, "SSR2")
        b.drift(0.20, ap)
        if cm in (1, 3, 5):    # laserwire stations at CM2/4/6
            b.wire(ap, kind="laserwire")
    b.toroid(ap)
    b.end()

    # ---- LB650: 9 CM x 4 cav @650 (5-cell, beta_G 0.61) + warm doublet
    # between CMs; 185 -> 516 MeV. Quad pipe (46 mm) is the tight aperture.
    ap_cav, ap_q = 0.0415, 0.023
    b.begin("LB650", 650.0)
    n_cav, phi = 36, -20.0
    v = (516.0 - 185.0) / (n_cav * math.cos(math.radians(phi)))
    for cm in range(9):
        b.drift(0.30, ap_cav)
        for _ in range(4):
            b.cavity(0.75, v, phi, 650.0, ap_cav, "LB650")
            b.drift(0.25, ap_cav)
        g = doublet_grad(b.w, 5.8, 0.20, 0.35)
        b.quad(0.20, g, ap_q)
        b.drift(0.35, ap_q)
        b.quad(0.20, -g, ap_q)
        b.corrector(ap_q); b.bpm(ap_q)
        b.blm()
        b.drift(0.30, ap_cav)
        if cm in (0, 2, 5, 8):  # laserwire stations at CM1/3/6/9
            b.wire(ap_cav, kind="laserwire")
    b.toroid(ap_cav)
    b.end()

    # ---- HB650: 4 CM x 6 cav @650 (5-cell, beta_G 0.92); 516 -> 800 MeV
    ap_cav, ap_q = 0.059, 0.023
    b.begin("HB650", 650.0)
    n_cav, phi = 24, -18.0
    v = (800.0 - 516.0) / (n_cav * math.cos(math.radians(phi)))
    for cm in range(4):
        b.drift(0.30, ap_cav)
        for j in range(6):
            b.cavity(1.10, v, phi, 650.0, ap_cav, "HB650")
            b.drift(0.25, ap_cav)
            if j == 2:
                b.blm()
        g = doublet_grad(b.w, 9.9, 0.20, 0.35)
        b.quad(0.20, g, ap_q)
        b.drift(0.35, ap_q)
        b.quad(0.20, -g, ap_q)
        b.corrector(ap_q); b.bpm(ap_q)
        b.blm()
        b.drift(0.30, ap_cav)
        if cm in (1, 3):        # laserwire stations at CM2/4
            b.wire(ap_cav, kind="laserwire")
    b.toroid(ap_cav)
    b.end()

    # ---- BTL: representative transfer line (real one is 308 m FODO with two
    # achromatic arcs + debuncher; modeled here as 6 FODO cells with 8 bends
    # at 0.24 T-class fields, below the Lorentz-stripping limit)
    ap = 0.0225  # 45 mm BPM bore
    b.begin("BTL")
    g_btl = 6.5  # T/m published class

    def fodo_cell(bends: int, debuncher: bool = False):
        b.quad(0.20, g_btl, ap)
        b.corrector(ap); b.bpm(ap)
        b.drift(1.60, ap)
        if debuncher:
            b.cavity(0.60, 1.3, -90.0, 650.0, ap, "debuncher")
            b.drift(0.40, ap)
        for _ in range(bends):
            b.add("dipole", f"BTL:B{b._n('B')}", 2.45, ap,
                  params={"angle_deg": 6.78, "b_t": 0.24})
            b.drift(0.40, ap)
        b.quad(0.20, -g_btl, ap)
        b.corrector(ap); b.bpm(ap)
        b.blm()
        b.drift(1.60, ap)

    fodo_cell(0)
    fodo_cell(0, debuncher=True)
    fodo_cell(2)
    fodo_cell(2)
    b.wire(ap)
    fodo_cell(2)
    fodo_cell(2)
    b.scraper(0.015)   # transverse collimation ahead of the foil
    b.toroid(ap)
    b.drift(0.5, ap)
    b.end()

    return {
        "meta": {
            "name": "PIP-II 800 MeV H- linac (virtual)",
            "version": "baseline-2026-07",
            "bunch_freq_mhz": 162.5,
            "nominal_current_ma": 2.0,     # post-chop average in-pulse
            "peak_current_ma": 5.0,        # pre-chop from RFQ
            "pulse_hz": 20.0,
            "pulse_ms": 0.55,              # injection window
            "beam_ms": 0.54,               # beam within the window
            "mass_mev": M_HMINUS,
            "loss_limit_wpm": 1.0,
            "loss_warn_wpm": 0.1,
            "emit_t_um": 0.20,             # rms norm transverse at RFQ exit
            "emit_l_um": 0.28,             # rms norm longitudinal
            "chop_fraction": 0.6,          # fraction of bunches removed
        },
        "sections": b.sections,
        "elements": b.elements,
    }


if __name__ == "__main__":
    doc = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    n = {t: sum(1 for e in doc["elements"] if e["type"] == t)
         for t in ("rfgap", "solenoid", "quad", "corrector", "bpm", "blm",
                   "toroid", "wire_scanner")}
    total = doc["elements"][-1]["s"] + doc["elements"][-1]["length"]
    print(f"wrote {OUT} — {len(doc['elements'])} elements, {total:.1f} m")
    print(n)
    print({s['name']: (s['w_in'], s['w_out']) for s in doc['sections']})
