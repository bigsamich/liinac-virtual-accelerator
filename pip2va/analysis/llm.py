"""Local-LLM narration of trip evidence via Ollama.

Uses the Ollama HTTP API (default http://localhost:11434, model from
PIP2VA_LLM_MODEL, default qwen3.6:latest). Falls back to the rule-based
summary when the server is unreachable.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import root_cause

OLLAMA_URL = os.environ.get("PIP2VA_OLLAMA_URL", "http://localhost:11434")
def _pick_model():
    forced = os.environ.get("PIP2VA_LLM_MODEL")
    if forced:
        return forced
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags",
                                    timeout=2) as r:
            names = [m["name"] for m in json.loads(r.read())["models"]]
        # ft student demoted until it passes the knowledge exam
        # (set PIP2VA_LLM_MODEL=pip2va-expert-ft to test it explicitly)
        for cand in ("pip2va-expert:latest",):
            if cand in names:
                return cand
    except Exception:
        pass
    return "qwen3.6:latest"


MODEL = _pick_model()
BAKED = MODEL.startswith("pip2va")   # KB insights live in the model

SYSTEM = """You are an expert accelerator operator and beam physicist on shift
at the PIP-II 800 MeV H- superconducting linac (LEBT, RFQ 162.5 MHz to
2.1 MeV, MEBT with chopper, then SRF sections HWR, SSR1, SSR2 at 325 MHz and
LB650, HB650 at 650 MHz, then BTL transfer line). The machine protection
system (MPS) has dropped the beam permit. You are given a JSON evidence pack:
the trip event, tripped devices with s-positions, active fault injections,
recent setpoint changes, RF/magnet deviations from design, and the loss
distribution. Beam physics facts: a tripped or detuned cavity makes the beam
arrive late and slip off-crest in every cavity downstream, collapsing the
energy profile and causing losses downstream of the failure; an off-design
quad/solenoid causes mismatch and slow envelope growth; a corrector or
steering error causes localized aperture scraping near the orbit peak.

Write a concise root-cause analysis for the operator:
1. ROOT CAUSE: the single most likely cause with the physics chain to the
   observed loss location (2-4 sentences).
2. ALTERNATIVES: up to two other candidates and what to check to rule them
   in/out.
3. ACTIONS: numbered recovery steps ending with the permit reset.
Be specific: name devices and s-positions from the evidence. No preamble."""


def available(url: str = OLLAMA_URL, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def analyze(evidence: dict, model: str = MODEL, url: str = OLLAMA_URL,
            timeout: float = 300.0) -> tuple[str, str]:
    """Returns (text, engine) where engine is 'llm:<model>' or 'rules'."""
    hints = root_cause.rule_based_summary(evidence)
    payload = {
        "model": model,
        "stream": False,
        "think": False,   # reasoning models: keep the answer in content
        "options": {"temperature": 0.2, "num_predict": 700},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                "Evidence pack:\n```json\n"
                + json.dumps(evidence, indent=1, default=str)[:24000]
                + "\n```\n\nRule-based first pass (verify or overturn it):\n"
                + hints},
        ],
    }
    req = urllib.request.Request(
        f"{url}/api/chat", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read())
        msg = out.get("message", {})
        text = (msg.get("content") or "").strip()
        if not text:  # some reasoning models answer via the thinking channel
            text = (msg.get("thinking") or "").strip()
        if not text:
            raise ValueError("empty LLM response")
        return text, f"llm:{model}"
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        return (hints + f"\n\n[local LLM unavailable ({e}); "
                "rule-based analysis shown]", "rules")
