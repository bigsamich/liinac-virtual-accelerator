"""Trip root-cause analysis: evidence collection + rule-based diagnosis.

collect_evidence() snapshots everything an operator would check after a trip:
the trip event itself, tripped devices, active fault injections, recent
setpoint changes (audit log), RF/magnet deviations from design, and the loss
distribution. rule_based_summary() turns that into an instant ranked
diagnosis; llm.py can narrate the same evidence with a local LLM.
"""
from __future__ import annotations

import re
import time

import numpy as np

from pip2va.common import audit, codec, keys
from pip2va.common.lattice import Lattice


def _decode_hash(r, key) -> dict:
    return {(k.decode() if isinstance(k, bytes) else k):
            (v.decode() if isinstance(v, bytes) else v)
            for k, v in r.hgetall(key).items()}


def collect_evidence(r, lat: Lattice) -> dict:
    ev: dict = {"t_now": time.time()}

    # --- the trip itself
    events = []
    for _, f in r.xrevrange(keys.stream("mps.events"), count=30):
        events.append({(k.decode() if isinstance(k, bytes) else k):
                       (v.decode() if isinstance(v, bytes) else v)
                       for k, v in f.items()})
    ev["recent_events"] = events
    trip = next((e for e in events if e.get("kind") == "trip"), None)
    ev["trip"] = trip
    trip_t = float(trip["t"]) if trip else time.time()
    loss_s = None
    if trip:
        m = re.match(r"(\S+)", trip.get("detail", ""))
        if m:
            ev["trip_blm"] = m.group(1)
            try:
                el = lat.by_name(m.group(1))
                loss_s = el.s
                ev["trip_blm_s_m"] = round(el.s, 2)
                ev["trip_blm_section"] = el.section
            except (StopIteration, KeyError):
                pass

    # --- tripped devices + deviations from design
    tripped, rf_anom, mag_anom = [], [], []
    for el in lat.elements:
        if el.type in ("rfgap", "rfq"):
            rb = _decode_hash(r, keys.readback("rf", el.name))
            if not rb:
                continue
            if rb.get("status") == "tripped":
                tripped.append({"device": el.name, "kind": "rf cavity",
                                "s_m": round(el.s, 2),
                                "upstream_of_loss": loss_s is None or el.s < loss_s})
                continue
            vd = el.params.get("v_mv", el.params.get("v_design", 1.0))
            pd = el.params.get("phi_deg", 0.0)
            try:
                da = float(rb.get("amp", vd)) - vd
                dp = float(rb.get("phase", pd)) - pd
                det = float(rb.get("detuning_hz", 0.0))
            except ValueError:
                continue
            if abs(da) > 0.03 * max(vd, 0.05) or abs(dp) > 3.0 or abs(det) > 60.0:
                rf_anom.append({"device": el.name, "s_m": round(el.s, 2),
                                "amp_dev_mv": round(da, 4),
                                "phase_dev_deg": round(dp, 2),
                                "detuning_hz": round(det, 1)})
        elif el.type in ("solenoid", "quad", "corrector"):
            rb = _decode_hash(r, keys.readback("magnet", el.name))
            if not rb:
                continue
            if rb.get("status") == "tripped":
                tripped.append({"device": el.name, "kind": "magnet",
                                "s_m": round(el.s, 2),
                                "upstream_of_loss": loss_s is None or el.s < loss_s})
                continue
            if el.type == "corrector":
                for fld in ("current_x", "current_y"):
                    try:
                        v = float(rb.get(fld, 0.0))
                    except ValueError:
                        continue
                    if abs(v) > 3.0:
                        mag_anom.append({"device": f"{el.name}:{fld}",
                                         "s_m": round(el.s, 2),
                                         "current_a": round(v, 2),
                                         "design_a": 0.0})
            else:
                d = el.params["design_current"]
                try:
                    v = float(rb.get("current", d))
                except ValueError:
                    continue
                if abs(v - d) > 0.03 * max(abs(d), 1.0):
                    mag_anom.append({"device": el.name, "s_m": round(el.s, 2),
                                     "current_a": round(v, 2),
                                     "design_a": round(d, 2)})
    ev["tripped_devices"] = tripped
    ev["rf_anomalies"] = rf_anom[:15]
    ev["magnet_anomalies"] = mag_anom[:15]

    # --- active fault injections (training scenarios)
    ev["active_fault_injections"] = [
        k.decode() if isinstance(k, bytes) else k
        for k in r.scan_iter("fault:*")]

    # --- recent setpoint changes before the trip
    changes = []
    for e in audit.read_log(r, 200):
        try:
            dt = float(e["t"]) - trip_t
        except (KeyError, ValueError):
            continue
        if -300.0 <= dt <= 1.0:   # five minutes before the trip
            changes.append({"dt_s": round(dt, 1), "key": e["key"],
                            "field": e.get("field"), "value": e.get("value"),
                            "source": e.get("source")})
    ev["setting_changes_before_trip"] = changes[:40]

    # --- beam + loss snapshot
    st = _decode_hash(r, "state:beam")
    ev["beam_state"] = st
    entries = r.xrevrange(keys.stream("blm.losses"), count=10)
    if entries:
        wpm = np.mean([codec.unpack(f[b"d"])[1]["wpm"] for _, f in entries],
                      axis=0)
        blms = lat.instruments("blm")
        top = np.argsort(wpm)[-5:][::-1]
        ev["top_losses"] = [
            {"blm": blms[j].name if j < len(blms) else f"BLM{j}",
             "s_m": round(blms[j].s, 2) if j < len(blms) else None,
             "wpm": round(float(wpm[j]), 3)} for j in top]
    return ev


def rule_based_summary(ev: dict) -> str:
    """Instant ranked diagnosis from the evidence — no LLM required."""
    lines = []
    trip = ev.get("trip")
    if not trip:
        return "No trip found in the event log."
    lines.append(f"TRIP: {trip.get('detail', '?')}")
    if ev.get("trip_blm_section"):
        lines.append(f"Loss location: {ev.get('trip_blm')} at "
                     f"s={ev.get('trip_blm_s_m')} m ({ev['trip_blm_section']})")
    hyp = []
    inj = ev.get("active_fault_injections") or []
    if inj:
        hyp.append(f"ACTIVE FAULT INJECTION present: {', '.join(inj)} — "
                   "training scenario is the most likely cause.")
    for d in ev.get("tripped_devices", []):
        if d.get("upstream_of_loss"):
            hyp.append(f"{d['kind']} {d['device']} is TRIPPED at s={d['s_m']} m, "
                       "upstream of the loss point — beam arrives off-energy/"
                       "off-phase downstream of it.")
    recent = [c for c in ev.get("setting_changes_before_trip", [])
              if c.get("source") != "autotune" and c["dt_s"] > -90]
    for c in recent[:3]:
        hyp.append(f"Setpoint change {abs(c['dt_s']):.0f}s before trip: "
                   f"{c['key']} {c['field']}={c['value']} ({c['source']}).")
    for a in ev.get("magnet_anomalies", [])[:3]:
        hyp.append(f"Magnet off design: {a['device']} at {a['current_a']} A "
                   f"(design {a['design_a']} A), s={a['s_m']} m.")
    for a in ev.get("rf_anomalies", [])[:3]:
        hyp.append(f"RF anomaly: {a['device']} amp dev {a['amp_dev_mv']} MV, "
                   f"phase dev {a['phase_dev_deg']} deg, "
                   f"detuning {a['detuning_hz']} Hz.")
    if not hyp:
        hyp.append("No device trips, injections, or recent setpoint changes "
                   "found — likely a slow drift or a marginal BLM threshold. "
                   "Check detuning trends and consider re-learning the "
                   "baseline after verifying losses.")
    lines.append("")
    lines.append("Ranked hypotheses:")
    lines += [f"  {i+1}. {h}" for i, h in enumerate(hyp[:6])]
    lines.append("")
    lines.append("Suggested actions: fix/reset the cause, then RESET the beam "
                 "permit. Autotune 'Rescue' restores all setpoints to design.")
    return "\n".join(lines)
