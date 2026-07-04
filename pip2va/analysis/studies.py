"""AI-planned beam studies.

Natural language ("sweep SSR2:CAV17 phase ±15 deg and amplitude ±5% over two
minutes") -> the local LLM compiles a structured, machine-validated scan plan
-> the autotune service executes it step by step with dwell, per-step
instrumentation capture, trip-abort, and restore -> the LLM (or rules) writes
the post-study report.

Plan schema (JSON):
{
  "name": str, "kind": "sweep" | "ramp",
  "description": str, "rationale": str,
  "sweeps": [{"cls": "rf|magnet|source|chopper", "device": str,
              "field": "phase|amp|current|current_x|current_y|current_ma|duty",
              "from": float, "to": float}],
  "steps": int, "dwell_s": float, "restore": bool
}
All sweeps share the same step grid (parallel multi-parameter scans).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

import numpy as np

from pip2va.common.lattice import load_lattice

from . import llm

VALID_FIELDS = {
    "rf": {"phase", "amp"},
    "magnet": {"current", "current_x", "current_y"},
    "source": {"current_ma"},
    "chopper": {"duty"},
}

PLAN_SYSTEM = """You are the beam-studies planner for a PIP-II 800 MeV H-
linac virtual accelerator (sections LEBT, RFQ, MEBT, HWR, SSR1, SSR2, LB650,
HB650, BTL; 20 Hz pulses). Convert the operator's request into ONE JSON study
plan, no prose, matching exactly this schema:

{"name": short-kebab-name, "kind": "sweep" or "ramp",
 "description": one sentence, "rationale": why these steps/dwell are right,
 "sweeps": [{"cls": "rf"|"magnet"|"source"|"chopper", "device": device-name,
             "field": field, "from": number, "to": number}],
 "steps": integer, "dwell_s": seconds-per-step, "restore": true/false}

Rules:
- rf devices: fields "amp" [MV] and "phase" [deg]; never exceed the quench
  limit given in the device catalog; phases in [-180, 180].
- magnet devices: field "current" [A] (correctors: "current_x"/"current_y",
  hard limit +/-10 A); stay inside the max_current given.
- source: device "main", field "current_ma" in [0, 15]; chopper: device
  "main", field "duty" in [0, 1].
- "sweep": settle at each point, restore=true (return to original settings).
- "ramp" (e.g. raising source current to a new operating point): restore=
  false, monotonic steps. Choose a SAFE rate: current changes <= 0.25 mA per
  step with dwell >= 2 s unless the operator insists; explain in rationale.
- steps*dwell_s should honor any requested total duration. dwell_s >= 0.5.
- If the request names a device loosely, pick the closest from the catalog.
Return ONLY the JSON object."""


def device_catalog(text: str) -> str:
    """Compact catalog of devices relevant to the request (+ limits)."""
    lat = load_lattice()
    toks = set(re.findall(r"[A-Za-z0-9:]+", text.upper()))
    lines = ["source main: current_ma 0..15 mA (nominal 5)",
             "chopper main: duty 0..1 (nominal 0.4)"]
    hits = 0
    for e in lat.elements:
        if e.type in ("rfgap", "rfq"):
            rel = any(t in e.name.upper() for t in toks) or hits < 0
            if rel and hits < 25:
                p = e.params
                lines.append(
                    f"rf {e.name}: amp design "
                    f"{p.get('v_mv', p.get('v_design', 1.0)):.3f} MV, quench "
                    f"{p.get('quench_mv', 0):.2f} MV, phase design "
                    f"{p.get('phi_deg', 0):.1f} deg")
                hits += 1
        elif e.type in ("solenoid", "quad", "corrector"):
            if any(t in e.name.upper() for t in toks) and hits < 25:
                lim = e.params.get("max_amp") or e.params.get("max_current", 0)
                lines.append(
                    f"magnet {e.name} ({e.type}): design "
                    f"{e.params.get('design_current', 0):.2f} A, "
                    f"limit +/-{lim:g} A")
                hits += 1
    if hits == 0:
        lines.append("families: HWR 8 cav (quench 2.1 MV), SSR1 16 (2.15), "
                     "SSR2 35 (5.25), LB650 36 (12.5), HB650 24 (20.9); "
                     "name cavities like SSR2:CAV17, magnets like LB650:Q5")
    return "\n".join(lines)


def plan_from_text(text: str, timeout: float = 240.0) -> tuple[dict, str]:
    """Returns (plan, note). Raises RuntimeError if the LLM is unreachable."""
    payload = {
        "model": llm.MODEL, "stream": False, "think": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 600},
        "messages": [
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content":
                f"Device catalog:\n{device_catalog(text)}\n\nRequest: {text}"},
        ],
    }
    req = urllib.request.Request(
        f"{llm.OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read())
        raw = (out.get("message", {}).get("content") or "").strip()
        plan = json.loads(raw)
    except (OSError, ValueError, KeyError) as e:
        raise RuntimeError(f"LLM planning failed: {e}") from e
    return validate_plan(plan)


def validate_plan(plan: dict) -> tuple[dict, str]:
    """Clamp to machine limits; returns (plan, human note)."""
    lat = load_lattice()
    notes = []
    plan["steps"] = int(np.clip(int(plan.get("steps", 10)), 2, 500))
    plan["dwell_s"] = float(np.clip(float(plan.get("dwell_s", 2.0)),
                                    0.5, 60.0))
    plan.setdefault("restore", plan.get("kind", "sweep") == "sweep")
    plan.setdefault("name", "study")
    sweeps = plan.get("sweeps", [])
    if not sweeps:
        raise ValueError("plan has no sweeps")
    for sw in sweeps:
        cls, dev, fld = sw.get("cls"), sw.get("device"), sw.get("field")
        if cls not in VALID_FIELDS or fld not in VALID_FIELDS[cls]:
            raise ValueError(f"invalid sweep target {cls}:{dev}:{fld}")
        lo, hi = -1e9, 1e9
        if cls == "rf":
            el = lat.by_name(dev)   # raises if unknown
            if fld == "amp":
                lo, hi = 0.0, el.params.get(
                    "quench_mv",
                    1.3 * el.params.get("v_mv",
                                        el.params.get("v_design", 1.0)))
            else:
                lo, hi = -180.0, 180.0
        elif cls == "magnet":
            el = lat.by_name(dev)
            lim = (el.params.get("max_amp", 10.0)
                   if el.type == "corrector"
                   else el.params.get("max_current", 2000.0))
            lo, hi = -lim, lim
        elif cls == "source":
            lo, hi = 0.0, 15.0
        elif cls == "chopper":
            lo, hi = 0.0, 1.0
        for k in ("from", "to"):
            v = float(sw[k])
            cv = float(np.clip(v, lo, hi))
            if cv != v:
                notes.append(f"{dev}:{fld} {k}={v:g} clamped to {cv:g}")
            sw[k] = cv
    dur = plan["steps"] * plan["dwell_s"]
    notes.append(f"duration ~{dur:.0f} s ({plan['steps']} steps x "
                 f"{plan['dwell_s']:.1f} s)")
    return plan, "; ".join(notes)


# ------------------------------------------------------------------ reports

def rule_report(plan: dict, result: dict) -> str:
    """Instant post-study analysis from the captured step data."""
    steps = result.get("steps", [])
    if not steps:
        return "No data captured."
    lines = [f"STUDY: {plan.get('name')} — {plan.get('description', '')}",
             f"kind={plan.get('kind')} steps={len(steps)} "
             f"dwell={plan.get('dwell_s')}s "
             f"status={result.get('status', '?')}", ""]
    t = np.array([s["transmission"] for s in steps])
    wl = np.array([s["worst_blm"] for s in steps])
    wt = np.array([s["w_tof"] for s in steps])
    orms = np.array([s["orbit_rms_mm"] for s in steps])
    best = int(np.argmin(wl + (1 - t) * 100))
    lines.append(f"transmission: {t.min():.4f}..{t.max():.4f}")
    lines.append(f"worst BLM: {wl.min():.3f}..{wl.max():.3f} W/m "
                 f"(peak at step {int(np.argmax(wl)) + 1})")
    lines.append(f"TOF energy: {wt.min():.1f}..{wt.max():.1f} MeV; "
                 f"orbit rms {orms.min():.2f}..{orms.max():.2f} mm")
    sw0 = plan["sweeps"][0]
    vals = [s["set_values"][0] for s in steps]
    lines.append(f"best operating point: step {best + 1} "
                 f"({sw0['device']}:{sw0['field']} = {vals[best]:g})")
    if result.get("status") == "aborted-trip":
        k = len(steps)
        lines.append(f"MPS TRIPPED at step {k}: "
                     f"{sw0['device']}:{sw0['field']} = {vals[-1]:g} — this "
                     "is the empirical limit; back off and use a slower "
                     "rate / smaller span past this point.")
    elif plan.get("kind") == "ramp":
        margin = 1.0 - wl.max()
        lines.append("ramp completed without trip; worst-BLM headroom "
                     f"{margin:+.2f} W/m vs the 1 W/m criterion — "
                     + ("rate could be increased."
                        if margin > 0.5 else "keep this rate."))
    return "\n".join(lines)


def llm_report(plan: dict, result: dict, timeout: float = 300.0
               ) -> tuple[str, str]:
    """LLM post-study narrative; falls back to the rule report."""
    hints = rule_report(plan, result)
    table = [{"step": i + 1, **{f"{sw['device']}:{sw['field']}":
                                round(s["set_values"][j], 4)
                                for j, sw in enumerate(plan["sweeps"])},
              "T": round(s["transmission"], 4),
              "worst_blm_wpm": round(s["worst_blm"], 3),
              "w_tof_mev": round(s["w_tof"], 2),
              "orbit_rms_mm": round(s["orbit_rms_mm"], 3)}
             for i, s in enumerate(result.get("steps", []))]
    system = ("You are an accelerator physicist writing a beam-study report "
              "for the PIP-II linac. Given the study plan and per-step "
              "measurements, write: 1. SUMMARY (what was scanned, what "
              "happened), 2. FINDINGS (optimum, trends, anomalies, physics "
              "interpretation), 3. RECOMMENDATION (operating point or safe "
              "ramp rate, next study). Be quantitative and concise.")
    payload = {"model": llm.MODEL, "stream": False, "think": False,
               "options": {"temperature": 0.3, "num_predict": 800},
               "messages": [
                   {"role": "system", "content": system},
                   {"role": "user", "content":
                       "Plan:\n" + json.dumps(plan, indent=1)
                       + "\n\nMeasurements:\n" + json.dumps(table, indent=0)
                       + "\n\nFirst-pass analysis:\n" + hints}]}
    req = urllib.request.Request(
        f"{llm.OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read())
        msg = out.get("message", {})
        text = (msg.get("content") or msg.get("thinking") or "").strip()
        if not text:
            raise ValueError("empty response")
        return text, f"llm:{llm.MODEL}"
    except (OSError, ValueError, KeyError) as e:
        return hints + f"\n\n[LLM unavailable ({e})]", "rules"
