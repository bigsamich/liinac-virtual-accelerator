"""Training scenarios: scripted fault campaigns, recovery scoring, and a
post-training review built from the machine's own audit trail."""
from __future__ import annotations

import json
import time
import urllib.request

from pip2va.common import audit

from . import llm

# Scenario schema: faults -> injected via fault:* keys (cleared by operator /
# TTL); settings -> sabotaged setpoints the operator must find and restore.
SCENARIOS = {
    "Cavity trip in the spokes": {
        "level": "easy",
        "desc": "An SSR2 cavity quenches. Diagnose which one, reset it, and "
                "recover the beam permit.",
        "faults": [("rf", "SSR2:CAV17", "trip", 1, 0)],
        "settings": [], "par": 60.0,
    },
    "Stuck tuner (detune)": {
        "level": "medium",
        "desc": "A cavity tuner walks 300 Hz off resonance. Find it from the "
                "RF page detuning column before losses trip the machine.",
        "faults": [("rf", "LB650:CAV22", "detune", 300.0, 0)],
        "settings": [], "par": 90.0,
    },
    "Drifting solenoid supply": {
        "level": "medium",
        "desc": "An HWR solenoid supply drifts at 6 A/min. Watch the orbit "
                "and losses walk; catch and correct it.",
        "faults": [("magnet", "HWR:SOL4", "drift", 6.0, 120)],
        "settings": [], "par": 120.0,
    },
    "Double fault": {
        "level": "hard",
        "desc": "A cavity trips WHILE a corrector drifts. Untangle which "
                "fault explains which symptom.",
        "faults": [("rf", "SSR1:CAV11", "trip", 1, 0),
                   ("magnet", "SSR2:C14", "drift", 4.0, 90)],
        "settings": [], "par": 180.0,
    },
    "HB650 quench at full gradient": {
        "level": "easy",
        "desc": "A high-beta cavity quenches at the top of the linac: 284 "
                "MeV of energy reach is at stake. Recover it.",
        "faults": [("rf", "HB650:CAV7", "trip", 1, 0)],
        "settings": [], "par": 60.0,
    },
    "RFQ running low": {
        "level": "medium",
        "desc": "The RFQ amplitude has been mis-set 7% low: transmission "
                "collapses at the front end. Find the knob and restore it.",
        "faults": [], "settings": [("rf", "RFQ:RFQ", "amp", 0.93)],
        "par": 90.0,
    },
    "Chopper misconfigured": {
        "level": "easy",
        "desc": "Someone left the chopper keep-fraction at 0.75: nearly "
                "double the current heads downstream and the loss pattern "
                "scales with it. Restore nominal chopping.",
        "faults": [], "settings": [("chopper", "main", "duty", 0.75)],
        "par": 90.0,
    },
    "Vacuum event": {
        "level": "hard",
        "desc": "A pressure burst raises residual-gas stripping machine-"
                "wide (watch the BLM baseline floor). Find the physics "
                "parameter that explains it and restore the vacuum.",
        "faults": [],
        "settings": [("physics", "main", "pressure_torr", 3e-7)],
        "par": 150.0,
    },
    "Source sag": {
        "level": "easy",
        "desc": "The ion source droops to 3.2 mA: every toroid reads low "
                "but nothing tripped. Spot it and bring the current back.",
        "faults": [], "settings": [("source", "main", "current_ma", 3.2)],
        "par": 60.0,
    },
    "Buncher trip": {
        "level": "easy",
        "desc": "A MEBT buncher drops out: the bunch lengthens into the HWR "
                "and low-energy losses climb. One TRIPPED flag on the RF "
                "page gives it away.",
        "faults": [("rf", "MEBT:CAV2", "trip", 1, 0)],
        "settings": [], "par": 60.0,
    },
    "Quad supply sag": {
        "level": "medium",
        "desc": "An LB650 doublet quad runs 8% low: the envelope beats and "
                "losses grow over several cryomodules with no fault flag "
                "anywhere. Compare readbacks against design.",
        "faults": [],
        "settings": [("magnet", "LB650:Q7", "current", "DESIGN*0.92")],
        "par": 120.0,
    },
    "Silent detune drift": {
        "level": "hard",
        "desc": "A spoke cavity sits 150 Hz off resonance — no trip, no "
                "alarm, just extra forward power and a whisper of phase "
                "error. Find it before the He-pressure shift makes it worse.",
        "faults": [("rf", "SSR2:CAV28", "detune", 150.0, 0)],
        "settings": [], "par": 180.0,
    },
    "Phase sabotage": {
        "level": "hard",
        "desc": "One SSR1 cavity phase is 12 degrees off design: energy is "
                "subtly wrong from that point on and downstream phases "
                "slip. Nothing is tripped. TOF energy is your friend.",
        "faults": [],
        "settings": [("rf", "SSR1:CAV5", "phase", "DESIGN+12")],
        "par": 240.0,
    },
    "Three-corrector walk": {
        "level": "hard",
        "desc": "Three trims across different sections were left at wrong "
                "values: the orbit has a slow wave through the machine. "
                "Find all three (or steer them out and re-baseline).",
        "faults": [],
        "settings": [("magnet", "SSR1:C6", "current_x", 1.8),
                     ("magnet", "SSR2:C10", "current_y", -1.5),
                     ("magnet", "LB650:C4", "current_x", 1.2)],
        "par": 240.0,
    },
    "Corrector runaway": {
        "level": "medium",
        "desc": "A BTL corrector supply drifts hard for one minute — the "
                "orbit walks toward the aperture in the most activation-"
                "sensitive section of the machine.",
        "faults": [("magnet", "BTL:C7", "drift", 8.0, 60)],
        "settings": [], "par": 120.0,
    },
}


def _resolve(val, r, cls, dev, fld):
    """Values like 'DESIGN*0.92' / 'DESIGN+12' resolve against the lattice."""
    if not isinstance(val, str):
        return float(val)
    from pip2va.common.lattice import load_lattice
    el = load_lattice().by_name(dev)
    design = (el.params.get("design_current", 0.0) if fld == "current"
              else el.params.get("phi_deg", 0.0) if fld == "phase"
              else el.params.get("v_mv", el.params.get("v_design", 1.0)))
    if "*" in val:
        return design * float(val.split("*")[1])
    if "+" in val:
        return design + float(val.split("+")[1])
    return design


def start(r, hub_inject, hub_set, name: str) -> None:
    sc = SCENARIOS[name]
    orig = []
    for cls, dev, fld, val in sc["settings"]:
        val = _resolve(val, r, cls, dev, fld)
        key = f"settings:{cls}:{dev}"
        cur = r.hget(key, fld)
        orig.append([cls, dev, fld, float(cur) if cur else 0.0, val])
        hub_set(cls, dev, fld, val)
    for cls, dev, typ, mag, ttl in sc["faults"]:
        hub_inject(cls, dev, typ, mag, ttl)
    r.hset("state:training", mapping={
        "scenario": name, "t0": time.time(), "active": 1, "score": -1.0,
        "orig": json.dumps(orig)})


def _settings_restored(r, st) -> bool:
    try:
        orig = json.loads(st.get("orig", "[]"))
    except ValueError:
        return True
    for cls, dev, fld, val0, _sab in orig:
        cur = r.hget(f"settings:{cls}:{dev}", fld)
        if cur is None:
            return False
        if abs(float(cur) - val0) > 0.05 * max(abs(val0), 1e-3):
            return False
    return True


def check(r) -> dict:
    st = {k.decode(): v.decode() for k, v in r.hgetall("state:training").items()}
    if not st or st.get("active") != "1":
        return st
    beam = {k.decode(): v.decode() for k, v in r.hgetall("state:beam").items()}
    permit = r.get("state:mps.permit") in (b"1", "1")
    faults = list(r.scan_iter("fault:*"))
    healthy = (permit and not faults
               and float(beam.get("transmission", 0)) > 0.99
               and _settings_restored(r, st))
    if healthy:
        elapsed = time.time() - float(st["t0"])
        r.hset("state:training", mapping={"active": 0, "score": elapsed})
        st.update(active="0", score=str(elapsed))
    return st


def grade(score: float, par: float) -> str:
    if score <= par:
        return "EXPERT — under par"
    if score <= 2 * par:
        return "OPERATOR — solid recovery"
    return "TRAINEE — review the fault-analysis workflow"


# --------------------------------------------------------------- review

def review(r, st: dict) -> str:
    """Post-training review: what was injected, what happened, and every
    change the operator (and automation) made, from the audit trail."""
    name = st.get("scenario", "?")
    sc = SCENARIOS.get(name, {})
    t0 = float(st.get("t0", 0))
    score = float(st.get("score", -1))
    t_end = t0 + max(score, 0)
    lines = [f"POST-TRAINING REVIEW — {name}",
             f"result: {'recovered in %.0f s' % score if score >= 0 else 'incomplete'}"
             f"  (par {sc.get('par', 0):.0f} s) — "
             f"{grade(score, sc.get('par', 60.0)) if score >= 0 else ''}", ""]
    lines.append("INJECTED:")
    for cls, dev, typ, mag, ttl in sc.get("faults", []):
        lines.append(f"  fault {typ} on {cls}:{dev} (mag {mag}, "
                     f"ttl {ttl or 'latched'})")
    for cls, dev, fld, val in sc.get("settings", []):
        lines.append(f"  sabotage {cls}:{dev}:{fld} -> {val}")

    lines.append("")
    lines.append("MACHINE TIMELINE (MPS events):")
    evs = []
    for _, f in r.xrevrange("stream:mps.events", count=200):
        e = {k.decode(): v.decode() for k, v in f.items()}
        try:
            te = float(e.get("t", 0))
        except ValueError:
            continue
        if t0 - 1 <= te <= t_end + 2:
            evs.append((te, e))
    for te, e in sorted(evs):
        lines.append(f"  +{te - t0:6.1f}s  {e.get('kind', ''):13s} "
                     f"{e.get('detail', '')[:70]}")

    lines.append("")
    lines.append("OPERATOR / AUTOMATION ACTIONS (audit trail):")
    acts = []
    for e in audit.read_log(r, 400):
        try:
            te = float(e.get("t", 0))
        except (TypeError, ValueError):
            continue
        if t0 - 1 <= te <= t_end + 2:
            acts.append((te, e))
    if not acts:
        lines.append("  (no setpoint changes recorded)")
    for te, e in sorted(acts):
        lines.append(f"  +{te - t0:6.1f}s  [{e.get('source', ''):>9s}] "
                     f"{e.get('key', '')}:{e.get('field', '')} "
                     f"= {e.get('value', '')}")
    return "\n".join(lines)


def llm_debrief(r, st: dict, timeout: float = 300.0) -> tuple[str, str]:
    """Instructor-style critique of the recovery, via the local LLM."""
    rev = review(r, st)
    sc = SCENARIOS.get(st.get("scenario", ""), {})
    system = ("You are a senior accelerator operations instructor debriefing "
              "a trainee after a fault scenario on the PIP-II linac virtual "
              "machine. Given the scenario, the machine timeline, and every "
              "action the trainee took, write: 1. WHAT HAPPENED (the fault "
              "physics and its signature), 2. WHAT THE TRAINEE DID WELL, "
              "3. WHAT TO DO FASTER NEXT TIME (concrete: which page/signal "
              "identifies this fault fastest), 4. VERDICT (one line). "
              "Be specific and constructive.")
    payload = {"model": llm.MODEL, "stream": False, "think": False,
               "options": {"temperature": 0.3, "num_predict": 700},
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content":
                             f"Scenario card: {json.dumps(sc)}\n\n{rev}"}]}
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
        return rev + f"\n\n[LLM unavailable ({e})]", "rules"
