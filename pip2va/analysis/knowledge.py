"""Study knowledge base: every completed beam study leaves a compact finding
that informs the AI study planner and the trip root-cause analyzer."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

KB_PATH = Path.home() / ".pip2va" / "studies" / "knowledge.jsonl"


def summarize_result(plan: dict, result: dict) -> dict:
    steps = result.get("steps", [])
    sw = plan["sweeps"][0]
    finding = {"t": time.time(), "name": plan.get("name"),
               "kind": plan.get("kind"), "status": result.get("status"),
               "device": f"{sw['cls']}:{sw['device']}:{sw['field']}",
               "span": [sw["from"], sw["to"]], "n_steps": len(steps)}
    if steps:
        t = np.array([s["transmission"] for s in steps])
        wl = np.array([s["worst_blm"] for s in steps])
        vals = [s["set_values"][0] for s in steps]
        best = int(np.argmin(wl + (1 - t) * 100))
        finding.update(
            best_value=round(float(vals[best]), 4),
            t_range=[round(float(t.min()), 4), round(float(t.max()), 4)],
            loss_range_wpm=[round(float(wl.min()), 3),
                            round(float(wl.max()), 3)])
        if result.get("status") == "aborted-trip":
            finding["trip_value"] = round(float(vals[-1]), 4)
            finding["summary"] = (
                f"{finding['device']} trips the MPS at {vals[-1]:g} "
                f"(scanned from {sw['from']:g}); best point {vals[best]:g}")
        else:
            finding["summary"] = (
                f"{finding['device']} scanned {sw['from']:g}..{sw['to']:g}: "
                f"best {vals[best]:g}, losses "
                f"{wl.min():.2f}..{wl.max():.2f} W/m, T "
                f"{t.min():.3f}..{t.max():.3f}")
    else:
        finding["summary"] = f"{finding['device']}: no data ({finding['status']})"
    return finding


def append(finding: dict):
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with KB_PATH.open("a") as f:
        f.write(json.dumps(finding) + "\n")


def load(n: int = 100) -> list[dict]:
    if not KB_PATH.exists():
        return []
    lines = KB_PATH.read_text().strip().splitlines()[-n:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


_EMB_CACHE: dict = {}


def _embed(texts):
    import urllib.request

    from . import llm
    req = urllib.request.Request(
        llm.OLLAMA_URL + "/api/embed",
        data=json.dumps({"model": "qwen3-embedding:8b",
                         "input": texts}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["embeddings"]


def context_semantic(query: str, n: int = 8) -> str:
    """Embedding retrieval over the KB (falls back to keyword matching)."""
    import numpy as np
    try:
        rows = load(600)
        keys_ = [f.get("summary", "")[:400] for f in rows]
        missing = [k for k in keys_ if k and k not in _EMB_CACHE]
        for i in range(0, len(missing), 64):
            batch = missing[i:i + 64]
            for k, v in zip(batch, _embed(batch)):
                _EMB_CACHE[k] = np.array(v)
        qv = np.array(_embed([query])[0])
        qv /= np.linalg.norm(qv) + 1e-9
        scored = []
        for f, k in zip(rows, keys_):
            if k in _EMB_CACHE:
                v = _EMB_CACHE[k]
                scored.append((float(qv @ v / (np.linalg.norm(v) + 1e-9)),
                               f))
        scored.sort(key=lambda x: -x[0])
        picks = [f for _, f in scored[:n]]
        return "\n".join("- " + f.get("summary", "") for f in picks)
    except Exception:
        return context(query, n)


def context(query: str, n: int = 8) -> str:
    """Compact prior-findings text relevant to query tokens (device names,
    sections). Empty string when nothing matches."""
    toks = {t for t in query.upper().replace(":", " ").split() if len(t) > 2}
    scored = []
    for f in load(200):
        hay = (f.get("device", "") + " " + f.get("name", "")).upper()
        score = sum(1 for t in toks if t in hay)
        if score:
            scored.append((score, f))
    scored.sort(key=lambda x: (-x[0], -x[1].get("t", 0)))
    picks = [f for _, f in scored[:n]] or load(3)
    if not picks:
        return ""
    return "\n".join("- " + f.get("summary", "") for f in picks)
