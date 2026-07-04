"""Pre-made beam studies: the standing measurement program.

Each preset is a ready-to-run plan plus a "teaches" note — which operational
situation the result informs. Completed runs feed the knowledge base that
the AI study planner and the trip analyzer both consult.
"""
from __future__ import annotations

PRESETS = {
    "phase-acceptance-ssr2": {
        "teaches": "how far a spoke-cavity phase can drift before losses "
                   "trip the machine (informs 'Stuck tuner' / detune trips)",
        "plan": {"name": "phase-acceptance-ssr2", "kind": "sweep",
                 "description": "SSR2:CAV17 phase +/-8 deg vs losses",
                 "sweeps": [{"cls": "rf", "device": "SSR2:CAV17",
                             "field": "phase", "from": -34.0, "to": -18.0}],
                 "steps": 11, "dwell_s": 2.0, "restore": True},
    },
    "amp-sensitivity-hb650": {
        "teaches": "energy and loss sensitivity to a single HB650 gradient "
                   "(informs quench-recovery priorities)",
        "plan": {"name": "amp-sensitivity-hb650", "kind": "sweep",
                 "description": "HB650:CAV7 amplitude +/-4% vs TOF energy",
                 "sweeps": [{"cls": "rf", "device": "HB650:CAV7",
                             "field": "amp", "from": 11.94, "to": 12.94}],
                 "steps": 9, "dwell_s": 2.0, "restore": True},
    },
    "source-ramp-4-6": {
        "teaches": "safe intensity-ramp procedure: current raises the whole loss "
                   "pattern, so the MPS is re-baselined at each plateau "
                   "(first campaign proved a bare ramp trips at +7.5%)",
        "plan": {"name": "source-ramp-4-6", "kind": "ramp",
                 "description": "source 5 -> 6 mA in gentle steps from the operating point",
                 "sweeps": [{"cls": "source", "device": "main",
                             "field": "current_ma", "from": 5.0, "to": 6.0}],
                 "steps": 5, "dwell_s": 3.0, "restore": True,
                 "rebaseline": True},
    },
    "chopper-duty-scan": {
        "teaches": "current vs duty and the loss pattern's current scaling "
                   "(informs 'Chopper misconfigured')",
        "plan": {"name": "chopper-duty-scan", "kind": "sweep",
                 "description": "chopper keep-fraction 0.30 -> 0.50",
                 "sweeps": [{"cls": "chopper", "device": "main",
                             "field": "duty", "from": 0.30, "to": 0.50}],
                 "steps": 9, "dwell_s": 2.0, "restore": True},
    },
    "corrector-response-ssr1": {
        "teaches": "orbit response and loss onset for a single trim "
                   "(informs steering budgets and drift trips)",
        "plan": {"name": "corrector-response-ssr1", "kind": "sweep",
                 "description": "SSR1:C3 x-trim -0.8 to +0.8 A orbit response",
                 "sweeps": [{"cls": "magnet", "device": "SSR1:C3",
                             "field": "current_x", "from": -0.8, "to": 0.8}],
                 "steps": 9, "dwell_s": 2.0, "restore": True},
    },
    "quad-scan-lb650": {
        "teaches": "envelope sensitivity to a doublet quad (informs 'Quad "
                   "supply sag' and matching diagnostics)",
        "plan": {"name": "quad-scan-lb650", "kind": "sweep",
                 "description": "LB650:Q7 +/-6% quad scan vs losses",
                 "sweeps": [{"cls": "magnet", "device": "LB650:Q7",
                             "field": "current", "from": 0.94, "to": 1.06}],
                 "steps": 9, "dwell_s": 2.0, "restore": True,
                 "_relative_design": True},
    },
    "rfq-amp-curve": {
        "teaches": "front-end transmission vs RFQ amplitude (informs 'RFQ "
                   "running low')",
        "plan": {"name": "rfq-amp-curve", "kind": "sweep",
                 "description": "RFQ amplitude 0.95 -> 1.02 transmission curve",
                 "sweeps": [{"cls": "rf", "device": "RFQ:RFQ",
                             "field": "amp", "from": 0.95, "to": 1.02}],
                 "steps": 8, "dwell_s": 2.0, "restore": True},
    },
    "lb650-doublet-matching-2d": {
        "teaches": "two-knob doublet matching in LB650 (informs 'Quad "
                   "supply sag' and envelope-beat diagnostics)",
        "plan": {"name": "lb650-doublet-matching-2d", "kind": "sweep",
                 "description": "LB650:Q7 up while Q8 down, +/-4% together",
                 "sweeps": [{"cls": "magnet", "device": "LB650:Q7",
                             "field": "current", "from": 0.96, "to": 1.04},
                            {"cls": "magnet", "device": "LB650:Q8",
                             "field": "current", "from": 1.04, "to": 0.96}],
                 "steps": 9, "dwell_s": 2.0, "restore": True,
                 "_relative_design": True},
    },
    "chopper-intensity-frontier": {
        "teaches": "raising delivered current beyond nominal via duty, with "
                   "MPS re-baselining at each plateau",
        "plan": {"name": "chopper-intensity-frontier", "kind": "ramp",
                 "description": "chopper duty 0.40 -> 0.60 with rebaseline",
                 "sweeps": [{"cls": "chopper", "device": "main",
                             "field": "duty", "from": 0.40, "to": 0.60}],
                 "steps": 5, "dwell_s": 3.0, "restore": True,
                 "rebaseline": True},
    },
    "rfq-amp-fine": {
        "teaches": "precision location of the RFQ operating optimum",
        "plan": {"name": "rfq-amp-fine", "kind": "sweep",
                 "description": "RFQ amplitude 0.98 -> 1.02 fine",
                 "sweeps": [{"cls": "rf", "device": "RFQ:RFQ",
                             "field": "amp", "from": 0.98, "to": 1.02}],
                 "steps": 9, "dwell_s": 2.0, "restore": True},
    },
    "hb650-energy-trim": {
        "teaches": "end-of-linac energy trim vs the BTL-entrance activation "
                   "constraint (the machine's tightest limit)",
        "plan": {"name": "hb650-energy-trim", "kind": "sweep",
                 "description": "HB650:CAV24 phase +/-10 deg vs BTL losses",
                 "sweeps": [{"cls": "rf", "device": "HB650:CAV24",
                             "field": "phase", "from": -28.0, "to": -8.0}],
                 "steps": 9, "dwell_s": 2.0, "restore": True},
    },
    "iso-current-2d": {
        "teaches": "trading source current against chopper duty at constant "
                   "delivered current (two intensity knobs together)",
        "plan": {"name": "iso-current-2d", "kind": "ramp",
                 "description": "source 4.5->5.5 mA with duty 0.45->0.36",
                 "sweeps": [{"cls": "source", "device": "main",
                             "field": "current_ma", "from": 4.5, "to": 5.5},
                            {"cls": "chopper", "device": "main",
                             "field": "duty", "from": 0.45, "to": 0.36}],
                 "steps": 5, "dwell_s": 3.0, "restore": True,
                 "rebaseline": True},
    },
    "buncher-phase-scan": {
        "teaches": "longitudinal capture sensitivity at the front end "
                   "(informs 'Buncher trip' and HWR loss patterns)",
        "plan": {"name": "buncher-phase-scan", "kind": "sweep",
                 "description": "MEBT:CAV1 phase -110 -> -70 deg",
                 "sweeps": [{"cls": "rf", "device": "MEBT:CAV1",
                             "field": "phase", "from": -110.0, "to": -70.0}],
                 "steps": 9, "dwell_s": 2.0, "restore": True},
    },
}


def get_plan(name: str) -> dict:
    """Preset plan, with DESIGN-relative sweeps resolved."""
    import copy

    from pip2va.common.lattice import load_lattice
    p = copy.deepcopy(PRESETS[name]["plan"])
    if p.pop("_relative_design", None):
        lat = load_lattice()
        for sw in p["sweeps"]:
            d = lat.by_name(sw["device"]).params.get("design_current", 0.0)
            sw["from"] = d * sw["from"]
            sw["to"] = d * sw["to"]
    return p
