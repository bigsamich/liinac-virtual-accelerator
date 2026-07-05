"""Operator Q&A assistant: answers free-form questions about the live
machine using a fresh evidence pack (state, losses, events, settings drift)
plus the study knowledge base. "What's the status?" / "what happens if I
raise the source current?" both route here."""
from __future__ import annotations

import json
import time
import urllib.request

import numpy as np

from pip2va.common import codec, keys
from pip2va.common.lattice import load_lattice

from . import knowledge, llm

SYSTEM = """You are the on-shift operations assistant for the PIP-II 800 MeV
H- superconducting linac virtual accelerator (LEBT -> RFQ 162.5 MHz ->
MEBT+chopper -> HWR -> SSR1 -> SSR2 (325 MHz) -> LB650 -> HB650 (650 MHz) ->
BTL transfer line; 20 Hz x 0.55 ms pulses, nominal 5 mA source / 2 mA
delivered). You receive a JSON snapshot of the live machine and a list of
MEASURED FINDINGS from this machine's own beam-study program. Answer the
operator's question concisely and concretely.

Rules:
- For status questions: lead with the headline numbers (energy, transmission,
  permit, worst loss + location), then anything abnormal.
- For "what happens if / can I" questions: reason from the MEASURED FINDINGS
  first (they are ground truth for THIS machine — tolerances, trip points,
  procedures), then general beam physics. Name the specific finding you used.
- If an action is risky, say what will trip and at roughly what value; if a
  validated procedure exists (e.g. re-baseline plateaus for intensity
  changes, neighbor compensation for dead cavities), prescribe it.
- Plain prose, no headers unless listing steps. 2-8 sentences unless the
  question genuinely needs more."""


def collect_context(r) -> dict:
    lat = load_lattice()
    ctx: dict = {"time": time.strftime("%Y-%m-%d %H:%M:%S")}
    st = {k.decode(): v.decode() for k, v in r.hgetall("state:beam").items()}
    if st:
        ctx["beam"] = {
            "energy_mev": round(float(st.get("w_out", 0)), 1),
            "transmission": round(float(st.get("transmission", 0)), 4),
            "delivered_ma": round(float(st.get("i_out_ma", 0)), 3),
            "engine_lag_ms": round(float(st.get("lag_ms", 0)), 1)}
    permit = r.get("state:mps.permit")
    ctx["beam_permit"] = "ON" if permit == b"1" else "TRIPPED/OFF"
    e = r.xrevrange(keys.stream("blm.losses"), count=5)
    if e:
        blms = lat.instruments("blm")
        wpm = np.mean([codec.unpack(f[b"d"])[1]["wpm"] for _, f in e], axis=0)
        j = int(np.argmax(wpm))
        top = np.argsort(wpm)[-3:][::-1]
        ctx["losses"] = {
            "worst": f"{blms[j].name} {wpm[j]:.1f} W/m",
            "top3": [f"{blms[k].name} {wpm[k]:.1f}" for k in top]}
    ctx["recent_events"] = [
        f.get(b"detail", b"").decode()[:90]
        for _, f in r.xrevrange(keys.stream("mps.events"), count=6)][::-1]
    try:
        from pip2va.common import snapshots
        diffs = snapshots.diff(snapshots.collect(r),
                               snapshots.load("golden"))
        ctx["settings_off_golden"] = [
            f"{k}: {a} -> {b}" for k, a, b in diffs[:8]]
        if len(diffs) > 8:
            ctx["settings_off_golden"].append(f"... and {len(diffs)-8} more")
    except Exception:
        pass
    stu = {k.decode(): v.decode() for k, v in r.hgetall("state:study").items()}
    if stu.get("run") == "1":
        ctx["study_running"] = stu.get("status", "")
    at = {k.decode(): v.decode() for k, v in r.hgetall("state:autotune").items()}
    if at.get("status"):
        ctx["autotune"] = at["status"][:90]
    return ctx


def ask(r, question: str, timeout: float = 240.0) -> tuple[str, str]:
    """Returns (answer, engine)."""
    ctx = collect_context(r)
    findings = knowledge.context(question, n=10)
    extra = "\n".join("- " + f.get("summary", "")
                      for f in knowledge.load(400)
                      if f.get("kind") == "insight")[-3000:]
    user = (f"LIVE MACHINE SNAPSHOT:\n{json.dumps(ctx, indent=1)}\n\n"
            f"MEASURED FINDINGS relevant to the question:\n"
            f"{findings or '(none matched)'}\n\n"
            f"DISTILLED OPERATIONAL INSIGHTS:\n{extra}\n\n"
            f"OPERATOR QUESTION: {question}")
    if not llm.available():
        lines = [f"[LLM offline — snapshot] permit {ctx['beam_permit']}"]
        if "beam" in ctx:
            b = ctx["beam"]
            lines.append(f"W={b['energy_mev']} MeV T={b['transmission']} "
                         f"I={b['delivered_ma']} mA")
        if "losses" in ctx:
            lines.append("worst loss: " + ctx["losses"]["worst"])
        return "\n".join(lines), "rules"
    payload = {"model": llm.MODEL, "stream": False, "think": False,
               "options": {"temperature": 0.3, "num_predict": 600},
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user}]}
    req = urllib.request.Request(
        f"{llm.OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        msg = json.loads(resp.read()).get("message", {})
    text = (msg.get("content") or msg.get("thinking") or "").strip()
    return text, f"llm:{llm.MODEL}"
