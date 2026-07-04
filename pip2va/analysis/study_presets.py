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
        "teaches": "safe source-current ramp rate and how losses scale with "
                   "current (informs intensity increases)",
        "plan": {"name": "source-ramp-4-6", "kind": "ramp",
                 "description": "source 5 -> 6 mA in gentle steps from the operating point",
                 "sweeps": [{"cls": "source", "device": "main",
                             "field": "current_ma", "from": 5.0, "to": 6.0}],
                 "steps": 9, "dwell_s": 2.5, "restore": True},
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
