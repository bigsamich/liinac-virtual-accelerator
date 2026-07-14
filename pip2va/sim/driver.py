"""Single-process synchronous simulation driver — the deterministic execution
model behind golden-master testing and the what-if branch engine.

Runs the physics in a FIXED order with no Redis and no threads, so the readout
for pulse N is a pure function of ``(settings snapshot at N, N)``. Combined with
the counter-based RNG (``common.rng``), two runs over the same scripted input
produce bit-identical readout streams, and two forked branches that share the
global seed see identical noise (Common Random Numbers).

The live distributed system (services + Redis) is for the running machine; this
driver is the same physics under a deterministic driver for tests, replay, and
branching.
"""
from __future__ import annotations

import numpy as np

from pip2va.common.config import Settings
from pip2va.common.devmodel import FirstOrderDevice
from pip2va.common.lattice import Lattice, load_lattice
from pip2va.physics.envelope import EnvelopeEngine

TAU = {"solenoid": 3.0, "quad": 0.8, "corrector": 0.3}
RIPPLE = {"solenoid": 3e-5, "quad": 5e-5, "corrector": 5e-5}
DRIFT_PER_HR = {"solenoid": 5e-5, "quad": 2e-4, "corrector": 0.0}


class SimDriver:
    """A deterministic, Redis-free pulse driver over the magnet devices + the
    envelope engine. Every stochastic value keys on ``(seed, pulse_id, eid)``."""

    def __init__(self, settings: Settings | None = None,
                 lattice: Lattice | None = None, seed: int | None = None):
        self.settings = settings or Settings()
        if seed is not None:
            self.settings = self.settings.model_copy(update={"global_seed": seed})
        self.lat = lattice or load_lattice()
        self.dt = 1.0 / self.settings.tick_hz
        # errors off for the deterministic driver (perfect-machine baseline);
        # noise still comes from the device models, deterministically.
        self.engine = EnvelopeEngine(self.lat)
        self.devices: list[tuple] = []          # (el, field, device)
        self.setpoints: dict[str, float] = {}   # "el:field" -> setpoint
        for el in self.lat.elements:
            if el.type in ("solenoid", "quad"):
                fields = [("current", float(el.params.get("design_current", 0.0)))]
            elif el.type == "corrector":
                fields = [("current_x", 0.0), ("current_y", 0.0)]
            else:
                continue
            for f, sp in fields:
                dev = FirstOrderDevice(sp, TAU[el.type], RIPPLE[el.type],
                                       DRIFT_PER_HR[el.type],
                                       eid=f"{el.name}:{f}")
                self.devices.append((el, f, dev))
                self.setpoints[f"{el.name}:{f}"] = sp
        self.pulse_id = 0
        self.src_current_ma: float | None = None
        self._foil_j = next((i for i, e in enumerate(self.lat.elements)
                             if e.type == "foil"), self.engine.n - 1)
        # injection knobs (not physics devices) — optimizable objective inputs
        self.inj_knobs = {"bump0_mm": 8.0, "decay_turns": 12.0, "duty": 0.4}

    # -- interactive/branch hook: change setpoints (applied on the next step) --
    def apply(self, setpoints: dict) -> None:
        for k, v in setpoints.items():
            if k.startswith("inj:"):
                self.inj_knobs[k[4:]] = float(v)
            else:
                self.setpoints[k] = float(v)

    # ------------------------------------------------------------- one pulse
    def step(self, beam_on: bool = True) -> dict:
        from pip2va.common import rng as _rng
        _rng.set_active_seed(self.settings.global_seed)   # this driver's universe
        self.pulse_id += 1
        pid = self.pulse_id
        device_state: dict[str, dict] = {}
        for el, f, dev in self.devices:
            sp = self.setpoints.get(f"{el.name}:{f}", dev.setpoint)
            rb = dev.step(self.dt, setpoint=sp, pulse_id=pid)
            cal = (el.params.get("field_per_amp") or el.params.get("grad_per_amp")
                   or el.params.get("bl_per_amp") or 0.0)
            d = device_state.setdefault(el.name, {})
            d[f] = rb
            d[f.replace("current", "field")] = rb * cal
        res = self.engine.run(device_state, current_ma=self.src_current_ma,
                              beam_on=beam_on)
        return self._readouts(res)

    def _readouts(self, res) -> dict:
        return {
            "pulse_id": self.pulse_id,
            "w_out": float(res.w[-1]),
            "transmission": float(res.transmission[-1]),
            "worst_blm": float(np.max(res.blm_wpm)) if len(res.blm_wpm) else 0.0,
            "inj_score": self._injection_score(res),
            "bpm_x": np.asarray(res.bpm_x, dtype=np.float64).copy(),
            "bpm_y": np.asarray(res.bpm_y, dtype=np.float64).copy(),
            "blm_wpm": np.asarray(res.blm_wpm, dtype=np.float64).copy(),
        }

    def _injection_score(self, res) -> float:
        """Booster injection figure of merit at the foil (same model the
        beam-physics service publishes), from the envelope + injection knobs."""
        from pip2va.physics import injection as _inj
        j = self._foil_j
        cm = res.current_ma
        i_out = float(cm[j] if hasattr(cm, "__len__") else cm)
        q = _inj.score(
            i_out_ma=i_out,
            eps_x_um=float(getattr(res, "emit_x_um", 0.0)),
            eps_y_um=float(getattr(res, "emit_y_um", 0.0)),
            sig_x_mm=float(res.sig_x[j]) * 1e3, sig_y_mm=float(res.sig_y[j]) * 1e3,
            cx_mm=float(res.cx[j]) * 1e3, cy_mm=float(res.cy[j]) * 1e3,
            dpp_rms=float(getattr(res, "dpp", 0.0) or 7e-4),
            bump0_mm=self.inj_knobs["bump0_mm"],
            decay_turns=self.inj_knobs["decay_turns"],
            notch_ok=True, duty=self.inj_knobs["duty"])
        return float(q["score"])

    # ------------------------------------------------------------- many pulses
    def run(self, n_pulses: int, inputs: dict | None = None) -> list[dict]:
        """Run ``n_pulses``; ``inputs`` maps pulse_id -> {"el:field": setpoint}.
        Setpoints apply *before* the pulse of that id (a fixed, deterministic
        rule — the commit-horizon injector generalizes this in sim.input)."""
        inputs = inputs or {}
        out = []
        for _ in range(n_pulses):
            nxt = self.pulse_id + 1
            if nxt in inputs:
                self.apply(inputs[nxt])
            out.append(self.step())
        return out
