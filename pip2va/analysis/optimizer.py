"""Black-box optimizer over the deterministic branch engine.

Because forked branches share Common Random Numbers, the objective is smooth and
deterministic — the noise that normally wrecks direct optimization on a
stochastic simulator is cancelled, so a plain pattern search converges. Each
candidate is evaluated from the *same* base snapshot with the *same* seed, so
scores are directly comparable. Used for injection auto-tune and orbit/loss
steering.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pip2va.sim import branch


@dataclass
class Knob:
    name: str        # setpoint key: "inj:bump0_mm" or "SSR1:C3:current_x"
    lo: float
    hi: float
    init: float      # current value (also the perturbation base for sensitivity)
    step: float


@dataclass
class OptResult:
    best: dict
    score: float
    baseline: float = 0.0
    history: list = field(default_factory=list)
    n_evals: int = 0


def maximize(base_snapshot, knobs, objective, n_pulses: int = 12,
             seed: int | None = None, iters: int = 40) -> OptResult:
    """Coordinate pattern search maximizing ``objective(metrics) -> float``."""
    x = {k.name: k.init for k in knobs}
    steps = {k.name: k.step for k in knobs}
    bounds = {k.name: (k.lo, k.hi) for k in knobs}

    def score(point):
        return objective(branch.evaluate(base_snapshot, point, n_pulses,
                                         seed=seed))

    best_s = score(x)
    baseline = best_s
    n = 1
    history = [(dict(x), best_s)]
    for _ in range(iters):
        improved = False
        for k in knobs:
            for sgn in (+1.0, -1.0):
                cand = dict(x)
                lo, hi = bounds[k.name]
                cand[k.name] = min(hi, max(lo, x[k.name] + sgn * steps[k.name]))
                if cand[k.name] == x[k.name]:
                    continue
                s = score(cand)
                n += 1
                if s > best_s:
                    best_s, x, improved = s, cand, True
                    history.append((dict(x), s))
        if not improved:
            steps = {kn: st * 0.5 for kn, st in steps.items()}
            if all(steps[k.name] < (bounds[k.name][1] - bounds[k.name][0]) * 1e-3
                   for k in knobs):
                break
    return OptResult(best=x, score=best_s, baseline=baseline,
                     history=history, n_evals=n)


def sensitivity(base_snapshot, knobs, metric: str, n_pulses: int = 8,
                seed: int | None = None) -> dict:
    """CRN finite-difference Jacobian d(metric)/d(knob) — low variance because
    perturbed and baseline runs share identical noise."""
    base_m = branch.evaluate(base_snapshot, {}, n_pulses, seed=seed)
    out = {}
    for k in knobs:
        eps = max((k.hi - k.lo) * 0.02, 1e-6)
        mp = branch.evaluate(base_snapshot, {k.name: k.init + eps}, n_pulses,
                             seed=seed)
        out[k.name] = (mp.get(metric, 0.0) - base_m.get(metric, 0.0)) / eps
    return out


# ---- presets ---------------------------------------------------------------

def autotune_injection(base_snapshot, n_pulses: int = 10,
                       seed: int | None = None, iters: int = 30) -> OptResult:
    """Maximize the Booster injection score over the painting knobs."""
    knobs = [
        Knob("inj:bump0_mm", 0.5, 25.0,
             base_snapshot.get("inj_knobs", {}).get("bump0_mm", 8.0), 3.0),
        Knob("inj:decay_turns", 5.0, 285.0,
             base_snapshot.get("inj_knobs", {}).get("decay_turns", 12.0), 20.0),
    ]
    return maximize(base_snapshot, knobs,
                    lambda m: m.get("inj_score_mean", 0.0),
                    n_pulses=n_pulses, seed=seed, iters=iters)
