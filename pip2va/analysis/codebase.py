"""Code-RAG: a semantic index over the pip2va source so the assistant can
answer *implementation* questions ("how do you measure BPMs?") by retrieving
and explaining the actual code — not just the physics. Uses the same
qwen3-embedding:8b model as the knowledge base.

Build the index with `python -m pip2va.analysis.codebase` (or `make
code-index`); it is stored at data/code_index.npz and loaded lazily. If the
index is absent, code retrieval simply returns "" and the assistant behaves
as before."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

_PKG = Path(__file__).resolve().parent.parent          # .../pip2va
_ROOT = _PKG.parent                                     # repo root
# shared/persistent location (mounted into the service containers, next to
# the knowledge base); the repo data/ copy is a fallback for native runs.
_INDEX = Path.home() / ".pip2va" / "studies" / "code_index.npz"
_FALLBACK = _ROOT / "data" / "code_index.npz"
_CACHE: dict = {"loaded": False, "vecs": None, "meta": None}


def iter_chunks(pkg: Path = _PKG):
    """Yield one chunk per top-level function / method / class definition."""
    for py in sorted(pkg.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            src = py.read_text()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        lines = src.splitlines()
        rel = str(py.relative_to(_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                continue
            lo = node.lineno
            hi = getattr(node, "end_lineno", lo) or lo
            text = "\n".join(lines[lo - 1:hi])
            if len(text) < 40:
                continue
            yield {"file": rel, "name": node.name, "lo": lo, "hi": hi,
                   "doc": (ast.get_docstring(node) or "")[:300],
                   "text": text[:2200]}


def build_index(out: Path = _INDEX) -> int:
    from .knowledge import _embed
    chunks = list(iter_chunks())
    texts = [f"{c['file']} :: {c['name']}\n{c['doc']}\n{c['text'][:1400]}"
             for c in chunks]
    vecs: list = []
    for i in range(0, len(texts), 32):
        vecs.extend(_embed(texts[i:i + 32]))
    vecs = np.asarray(vecs, dtype=np.float32)
    meta = np.array([{k: c[k] for k in ("file", "name", "lo", "hi", "text")}
                     for c in chunks], dtype=object)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, vecs=vecs, meta=meta)
    return len(chunks)


def _load() -> bool:
    if not _CACHE["loaded"]:
        _CACHE["loaded"] = True
        path = _INDEX if _INDEX.exists() else (
            _FALLBACK if _FALLBACK.exists() else None)
        if path is not None:
            d = np.load(path, allow_pickle=True)
            _CACHE["vecs"] = d["vecs"]
            _CACHE["meta"] = list(d["meta"])
    return _CACHE["vecs"] is not None


def code_context(query: str, n: int = 3, min_sim: float = 0.5) -> str:
    """Return the most relevant source snippets for the query, or "" if the
    index is missing or nothing is clearly relevant (so machine-physics
    questions don't get spurious code injected)."""
    if not _load():
        return ""
    from .knowledge import _embed
    try:
        q = np.asarray(_embed([query])[0], dtype=np.float32)
    except Exception:
        return ""
    v = _CACHE["vecs"]
    sims = (v @ q) / (np.linalg.norm(v, axis=1) * np.linalg.norm(q) + 1e-9)
    order = np.argsort(sims)[::-1][:n]
    hits = [(float(sims[i]), _CACHE["meta"][i]) for i in order
            if sims[i] >= min_sim]
    if not hits:
        return ""
    out = ["RELEVANT SOURCE CODE from this simulator (cite file:line):"]
    for _s, m in hits:
        out.append(f"\n# {m['file']}:{m['lo']}  ({m['name']})\n{m['text'][:1400]}")
    return "\n".join(out)


if __name__ == "__main__":
    print(f"indexing {_PKG} …")
    n = build_index()
    print(f"built {n} code chunks -> {_INDEX}")
