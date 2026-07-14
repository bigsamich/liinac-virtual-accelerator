"""What-if branch engine — the payoff primitive.

Fork K deterministic branches from one snapshot, apply a different setpoint
delta in each, run them forward, and compare. All branches share the same
global seed, so they see *identical* noise (Common Random Numbers): the
difference between two branches is pure signal from the setpoint delta, not RNG
variance. That is what makes sensitivity estimates and the optimizer converge.

Branches are independent, so they parallelize across processes with no shared
state (the partial-order / DAG argument: nothing observes another branch's
ordering). ``workers=1`` runs them serially; both paths give identical results.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import snapshot


@dataclass
class BranchResult:
    label: str
    delta: dict
    metrics: dict
    stream: list | None = None


def metrics_of(stream: list[dict]) -> dict:
    """Aggregate a readout stream into scalar figures of merit."""
    if not stream:
        return {}
    wb = np.array([s["worst_blm"] for s in stream])
    tr = np.array([s["transmission"] for s in stream])
    inj = np.array([s.get("inj_score", 0.0) for s in stream])
    return {
        "worst_blm_mean": float(wb.mean()),
        "worst_blm_max": float(wb.max()),
        "transmission_min": float(tr.min()),
        "transmission_mean": float(tr.mean()),
        "inj_score_mean": float(inj.mean()),
        "orbit_rms_mm": float(np.sqrt(np.mean(np.concatenate(
            [s["bpm_x"] ** 2 + s["bpm_y"] ** 2 for s in stream])))),
        "n_pulses": len(stream),
    }


def _run_branch(args):
    base_snap, delta, n_pulses, seed, label, keep_stream = args
    from pip2va.sim.driver import SimDriver          # import inside for spawn
    d = SimDriver(seed=seed)
    snapshot.restore(d, base_snap)
    if seed is not None:
        d.settings = d.settings.model_copy(update={"global_seed": seed})
    if delta:
        d.apply(delta)
    stream = d.run(n_pulses, {})
    return BranchResult(label, delta or {}, metrics_of(stream),
                        stream if keep_stream else None)


def fork(base_snapshot: dict, deltas: list[dict], n_pulses: int,
         seed: int | None = None, workers: int = 1,
         labels: list[str] | None = None,
         keep_stream: bool = False) -> list[BranchResult]:
    """Fork one branch per delta from ``base_snapshot``, run ``n_pulses`` each.

    seed=None -> inherit the base snapshot's seed (true CRN across branches)."""
    if seed is None:
        seed = base_snapshot.get("global_seed")
    labels = labels or [f"branch{i}" for i in range(len(deltas))]
    args = [(snapshot.clone(base_snapshot), d, n_pulses, seed, lb, keep_stream)
            for d, lb in zip(deltas, labels)]
    if workers <= 1 or len(args) <= 1:
        return [_run_branch(a) for a in args]
    import multiprocessing as mp
    with mp.Pool(min(workers, len(args))) as pool:
        return pool.map(_run_branch, args)


def evaluate(base_snapshot: dict, setpoints: dict, n_pulses: int,
             seed: int | None = None) -> dict:
    """Single-branch action->observation for the optimizer: apply ``setpoints``,
    run, return metrics. Deterministic and CRN-shared with siblings."""
    return fork(base_snapshot, [setpoints], n_pulses, seed=seed)[0].metrics
