"""Instrumentation simulator: turns ground truth into measurements.

Reads truth:beam each pulse, applies per-instrument noise/calibration models
from the lattice, and publishes the measurement streams the GUI consumes:
  stream:bpm.orbit       x, y [m], phase [deg], sum [mA]
  stream:blm.losses      wpm [W/m]
  stream:toroid.current  i_ma [mA]
  stream:profile.scan    animated wire-scanner scans (on req:wire:{name})
Beam off -> instruments read their noise floors, like a real machine.
"""
from __future__ import annotations

import numpy as np

from pip2va.common import codec, keys
from pip2va.services.base import Service, main_for


class DiagSimService(Service):
    name = "diag-sim"

    def on_start(self):
        self.rng = np.random.default_rng(20260703)
        self.bpms = self.lat.instruments("bpm")
        self.blms = self.lat.instruments("blm")
        self.tors = self.lat.instruments("toroid")
        self.wss = {e.name: e for e in self.lat.instruments("wire_scanner")}
        self.i_nom = self.lat.meta.get("nominal_current_ma", 2.0)
        self._scan = None  # active wire scan state

    def on_tick(self, pulse_id: int):
        blob = self.r.hget(keys.truth("beam"), "d")
        if blob is None:
            return
        _, tr = codec.unpack(blob)
        rng = self.rng
        nb = len(self.bpms)

        # BPMs: position noise grows as charge drops toward the noise floor
        q = np.maximum(tr["bpm_sum"], 1e-4)
        scale = np.sqrt(np.minimum(self.i_nom / q, 400.0))
        pos_sig = np.array([b.params.get("noise_um", 10.0)
                            for b in self.bpms]) * 1e-6 * scale
        ph_sig = np.array([b.params.get("phase_noise_deg", 0.3)
                           for b in self.bpms]) * scale
        x = tr["bpm_x"] + rng.normal(0, pos_sig)
        y = tr["bpm_y"] + rng.normal(0, pos_sig)
        ph = tr["bpm_phase"] + rng.normal(0, ph_sig)
        i_noise = np.array([b.params.get("intensity_noise_frac", 0.01)
                            for b in self.bpms])
        ssum = np.maximum(tr["bpm_sum"] * (1 + rng.normal(0, i_noise))
                          + rng.normal(0, 0.002, nb), 0.0)
        self.publish_stream("bpm.orbit", pulse_id,
                            {"x": x, "y": y, "phase": ph, "sum": ssum})

        # BLMs
        frac = np.array([b.params.get("noise_frac", 0.05) for b in self.blms])
        dark = np.array([b.params.get("dark_wpm", 1e-3) for b in self.blms])
        wpm = np.maximum(tr["blm_wpm"] * (1 + rng.normal(0, frac))
                         + rng.normal(dark, dark), 0.0)
        self.publish_stream("blm.losses", pulse_id, {"wpm": wpm})

        # Toroids
        tfr = np.array([t.params.get("noise_frac", 0.002) for t in self.tors])
        tfl = np.array([t.params.get("floor_ma", 0.005) for t in self.tors])
        i_ma = np.maximum(tr["toroid_i"] * (1 + rng.normal(0, tfr))
                          + rng.normal(0, tfl), 0.0)
        self.publish_stream("toroid.current", pulse_id, {"i_ma": i_ma})

        self._wire_scans(pulse_id)

    # -------------------------------------------------------- wire scanners

    def _wire_scans(self, pulse_id: int):
        if self._scan is None:
            for name in self.wss:
                if self.r.exists(f"req:wire:{name}"):
                    prof = self._deep_profile(name)
                    if prof is None:
                        self.r.delete(f"req:wire:{name}")
                        continue
                    hx, hy, edges = prof
                    self._scan = {"name": name, "step": 0, "hx": hx, "hy": hy,
                                  "pos": 0.5 * (edges[:-1] + edges[1:])}
                    break
        if self._scan is None:
            return
        sc = self._scan
        # wire steps 2 bins per pulse; publish the partial scan
        sc["step"] = min(sc["step"] + 2, len(sc["pos"]))
        k = sc["step"]
        noise = self.rng.normal(0, 0.01 * max(sc["hx"].max(), 1e-9), k)
        done = 1.0 if k >= len(sc["pos"]) else 0.0
        self.publish_stream("profile.scan", pulse_id, {
            "name": sc["name"], "done": done,
            "pos_mm": sc["pos"][:k],
            "ix": np.maximum(sc["hx"][:k] + noise, 0.0),
            "iy": np.maximum(sc["hy"][:k] + noise, 0.0)})
        if done:
            self.r.delete(f"req:wire:{sc['name']}")
            self._scan = None

    def _deep_profile(self, name: str):
        entries = self.r.xrevrange(keys.stream("beam.deep"), count=1)
        if not entries:
            return None
        _, data = codec.unpack(entries[0][1][b"d"])
        kx, ky, ke = f"prof:{name}:x", f"prof:{name}:y", f"prof:{name}:edges"
        if kx not in data:
            return None
        return data[kx], data[ky], data[ke]


if __name__ == "__main__":
    main_for(DiagSimService)
