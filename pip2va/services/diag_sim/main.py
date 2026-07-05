"""Instrumentation simulator: turns ground truth into measurements.

Reads truth:beam each pulse, applies per-instrument noise/calibration models
from the lattice, and publishes the measurement streams the GUI consumes:
  stream:bpm.orbit       x, y [m], phase [deg], sum [mA]   (pulse averages)
  stream:blm.losses      wpm [W/m]
  stream:toroid.current  i_ma [mA]
  stream:profile.scan    animated wire-scanner scans (on req:wire:{name})
Intra-pulse waveforms (1000 samples / 0.55 ms window):
  stream:wf.toroid       every toroid, every pulse
  stream:wf.capture      devices selected in settings:wfsel:main, every pulse
  wf:postmortem          all BLM + toroid waveforms of the trip pulse
Beam off -> instruments read their noise floors, like a real machine.
"""
from __future__ import annotations

import numpy as np

from pip2va.common import codec, keys
from pip2va.services.base import Service, main_for

from .waveforms import WaveformSynth, t_ms


class DiagSimService(Service):
    name = "diag-sim"
    extra_channels = (keys.CH_MPS,)

    def on_start(self):
        from pip2va.common.lattice import load_errors
        self.rng = np.random.default_rng(20260703)
        self.errors = load_errors()
        self.bpms = self.lat.instruments("bpm")
        self._bpm_off_x = np.array([
            self.errors.get(b.name, {}).get("offset_x", 0.0)
            for b in self.bpms])
        self._bpm_off_y = np.array([
            self.errors.get(b.name, {}).get("offset_y", 0.0)
            for b in self.bpms])
        self._bpm_scale = np.array([
            self.errors.get(b.name, {}).get("scale", 1.0)
            for b in self.bpms])
        self.blms = self.lat.instruments("blm")
        self.tors = self.lat.instruments("toroid")
        self.wss = {e.name: e for e in self.lat.instruments("wire_scanner")}
        from pip2va.common.laserwire import stations as lw_stations
        self.lws = dict(lw_stations(self.lat))     # name -> s [m]
        self._lwscan = None
        self._cycle = None
        self.i_nom = self.lat.meta.get("nominal_current_ma", 2.0)
        self._scan = None  # active wire scan state
        self.synth = WaveformSynth(self.rng)
        # field-emission mapping: each cavity's radiation lands on its
        # nearest BLM (x-ray/dark-current background, W/m-equivalent units)
        cavs = [e for e in self.lat.elements if e.type in ("rfgap", "rfq")]
        blm_s = np.array([b.s for b in self.blms]) if self.blms else np.zeros(1)
        self._cav_blm = np.array([int(np.argmin(np.abs(blm_s - c.s)))
                                  for c in cavs])
        self.fe_wpm_per_unit = 0.02
        self._bpm_by_name = {e.name: k for k, e in enumerate(self.bpms)}
        self._blm_by_name = {e.name: k for k, e in enumerate(self.blms)}
        self._tor_by_name = {e.name: k for k, e in enumerate(self.tors)}
        self._last_blm_wf: dict[str, np.ndarray] = {}
        self._last_tor_wf: dict[str, np.ndarray] = {}
        self._last_pid = 0

    def on_event(self, channel, data):
        if channel == keys.CH_MPS and isinstance(data, dict) \
                and not data.get("permit", 1):
            self._dump_postmortem()

    def on_tick(self, pulse_id: int):
        blob = self.r.hget(keys.truth("beam"), "d")
        if blob is None:
            return
        _, tr = codec.unpack(blob)
        rng = self.rng
        nb = len(self.bpms)
        # LCW temperature -> rack electronics drift (research: ~2 deg phase
        # per 6 C uncalibrated; active cal leaves 0.2 deg/6 C class). We
        # model the calibrated residual + a small position-offset drift.
        if pulse_id % 20 == 0 or not hasattr(self, "_lcw_dT"):
            import json as _json
            u = self.r.get("state:util")
            try:
                self._lcw_dT = float(
                    _json.loads(u).get("lcw_c", 35.0)) - 35.0 if u else 0.0
            except ValueError:
                self._lcw_dT = 0.0
        lcw_phase_deg = 0.033 * self._lcw_dT      # residual after cal
        lcw_pos_m = 2.0e-6 * self._lcw_dT          # 2 um/C common-mode

        # BPMs: position noise grows as charge drops toward the noise floor
        q = np.maximum(tr["bpm_sum"], 1e-4)
        scale = np.sqrt(np.minimum(self.i_nom / q, 400.0))
        pos_sig = np.array([b.params.get("noise_um", 10.0)
                            for b in self.bpms]) * 1e-6 * scale
        ph_sig = np.array([b.params.get("phase_noise_deg", 0.3)
                           for b in self.bpms]) * scale
        # electrical offset + scale systematics; a BPM cannot report a
        # position beyond its own bore
        ap = np.array([b.aperture_radius for b in self.bpms])
        x = np.clip((tr["bpm_x"] + self._bpm_off_x + lcw_pos_m)
                    * self._bpm_scale + rng.normal(0, pos_sig), -ap, ap)
        y = np.clip((tr["bpm_y"] + self._bpm_off_y + lcw_pos_m)
                    * self._bpm_scale + rng.normal(0, pos_sig), -ap, ap)
        ph = tr["bpm_phase"] + lcw_phase_deg + rng.normal(0, ph_sig)
        i_noise = np.array([b.params.get("intensity_noise_frac", 0.01)
                            for b in self.bpms])
        ssum = np.maximum(tr["bpm_sum"] * (1 + rng.normal(0, i_noise))
                          + rng.normal(0, 0.002, nb), 0.0)
        # TOF energy: derived from BPM phase pairs; noise per
        # dE/E = gamma(gamma+1) * dphi*beta*c/(2*pi*f*L)  (arXiv:2509.14214)
        w_true = tr.get("bpm_w")
        if w_true is not None and len(w_true):
            gam = 1.0 + w_true / 939.294
            bet = np.sqrt(np.maximum(1 - 1 / gam ** 2, 1e-9))
            s_pos = np.array([b.s for b in self.bpms])
            L = np.maximum(np.gradient(s_pos), 0.5)
            dphi = np.radians(ph_sig)
            rel = gam * (gam + 1) * dphi * bet * 3e8 / (
                2 * np.pi * 162.5e6 * L)
            sys_rel = gam * (gam + 1) * np.radians(lcw_phase_deg) \
                * bet * 3e8 / (2 * np.pi * 162.5e6 * L)
            w_tof = np.maximum(
                w_true * (1 + sys_rel
                          + rng.normal(0, np.minimum(rel, 0.05))), 0.0)
        else:
            w_tof = np.zeros(nb)
        self.publish_stream("bpm.orbit", pulse_id,
                            {"x": x, "y": y, "phase": ph, "sum": ssum,
                             "w_tof": w_tof})

        # BLMs
        frac = np.array([b.params.get("noise_frac", 0.05) for b in self.blms])
        dark = np.array([b.params.get("dark_wpm", 1e-3) for b in self.blms])
        wpm = np.maximum(tr["blm_wpm"] * (1 + rng.normal(0, frac))
                         + rng.normal(dark, dark), 0.0)
        # field-emission background from the RF system (present with RF on,
        # beam or no beam — grows exponentially with pushed gradients)
        e_rf = self.r.xrevrange("stream:rf.cavity", count=1)
        if e_rf:
            _, rfd = codec.unpack(e_rf[0][1][b"d"])
            rad = rfd.get("rad")
            if rad is not None and len(rad) == len(self._cav_blm):
                np.add.at(wpm, self._cav_blm,
                          rad * self.fe_wpm_per_unit)
        self.publish_stream("blm.losses", pulse_id, {"wpm": wpm})

        # Toroids
        tfr = np.array([t.params.get("noise_frac", 0.002) for t in self.tors])
        tfl = np.array([t.params.get("floor_ma", 0.005) for t in self.tors])
        i_ma = np.maximum(tr["toroid_i"] * (1 + rng.normal(0, tfr))
                          + rng.normal(0, tfl), 0.0)
        self.publish_stream("toroid.current", pulse_id, {"i_ma": i_ma})

        self._waveforms(pulse_id, tr, i_ma, wpm)
        self._wcm(pulse_id, tr)
        self._wire_scans(pulse_id)
        self._lw_scans(pulse_id, tr)
        self._profiler_cycle(pulse_id)

    # ------------------------------------------------- wall current monitors

    WCM_N = 160          # bunches per published snapshot window

    def _wcm(self, pulse_id: int, tr: dict):
        """Resistive WCMs (PIP2IT style, flat to ~4 GHz): bunch-by-bunch
        charge for a rotating window of 160 consecutive 162.5 MHz buckets.
        MEBT:WCM1 sits after the chopper (sees the kept/chopped pattern and
        1e-4-level extinction of removed bunches); LEBT-side structure is
        unchopped so BTL:WCM1 shows the delivered train."""
        st = self.read_hash(keys.settings("chopper", "main"))
        src = self.read_hash(keys.settings("source", "main"))
        i_src = float(src.get("current_ma", 5.0))
        beam_on = bool(tr.get("beam_on", 1)) if isinstance(
            tr.get("beam_on", 1), (int, float)) else True
        # bunch charge at 162.5 MHz from source current [nC/bunch]
        q_full = i_src * 1e-3 / 162.5e6 * 1e9
        n = self.WCM_N
        # the ACTUAL programmed pattern from the bunch pattern generator
        from pip2va.common import bpg
        bucket0 = pulse_id * self.WCM_N % 65536
        pat = bpg.pattern_bits(st, n, bucket0)          # delivered
        pat_prog = bpg.programmed_bits(st, n, bucket0)   # reference
        extinction = 10 ** self.rng.normal(-4.0, 0.15)   # chopped leakage
        jitter = self.rng.normal(1.0, 0.01, n)           # bunch-charge noise
        q_mebt = np.where(pat, q_full, q_full * extinction) * jitter
        # transmission to the BTL applies to the kept bunches
        t_end = float(tr.get("transmission", [1.0])[-1]) \
            if hasattr(tr.get("transmission", 1.0), "__len__") else 1.0
        q_btl = q_mebt * t_end * self.rng.normal(1.0, 0.008, n)
        if not beam_on:
            q_mebt = np.abs(self.rng.normal(0, 2e-5, n))
            q_btl = np.abs(self.rng.normal(0, 2e-5, n))
        # bunch length from truth sigma_z at each monitor [ps]
        sz = tr.get("wcm_sig_ps")
        sig_mebt = float(sz[0]) if sz is not None else 380.0
        sig_btl = float(sz[1]) if sz is not None and len(sz) > 1 else 28.0
        # pattern verification: measured (WCM) vs programmed bits
        meas = q_mebt > 0.5 * max(q_full, 1e-9)
        mismatch = int(np.sum(meas != pat_prog)) if beam_on else 0
        self._bpg_bad = getattr(self, "_bpg_bad", 0)
        self._bpg_bad = self._bpg_bad + 1 if mismatch else 0
        self.r.hset("state:bpg", mapping={
            "programmed_duty": round(float(np.mean(pat_prog)), 4),
            "measured_duty": round(float(np.mean(meas)), 4),
            "mismatch_buckets": mismatch, "mode": st.get("mode", "duty")})
        if self._bpg_bad == 60:      # ~3 s persistent: warn, don't trip
            self.r.xadd(keys.stream("mps.events"),
                        {"t": __import__("time").time(), "kind": "bpg",
                         "detail": f"bunch-pattern mismatch: {mismatch} "
                                   f"buckets differ from programmed "
                                   f"pattern (chopper fault?)"},
                        maxlen=500, approximate=True)
        self.publish_stream("wf.wcm", pulse_id, {
            "bucket0": np.array([bucket0]),
            "pat": pat_prog.astype(np.float32),
            "MEBT:WCM1:q_nc": q_mebt.astype(np.float32),
            "MEBT:WCM1:sig_ps": np.array([sig_mebt], dtype=np.float32),
            "BTL:WCM1:q_nc": q_btl.astype(np.float32),
            "BTL:WCM1:sig_ps": np.array([sig_btl], dtype=np.float32)})

    # ----------------------------------------------------------- waveforms

    def _waveforms(self, pulse_id: int, tr: dict, i_ma, wpm):
        self._last_pid = pulse_id
        # toroids: full waveforms every pulse
        tor_wf = {}
        for k, el in enumerate(self.tors):
            wf = self.synth.toroid(
                float(i_ma[k]) if k < len(i_ma) else 0.0,
                el.params.get("noise_frac", 0.002),
                el.params.get("floor_ma", 0.005))
            tor_wf[el.name] = wf
        self._last_tor_wf = tor_wf
        self.publish_stream("wf.toroid", pulse_id,
                            {"t_ms": t_ms(), **tor_wf})

        # BLM waveforms kept for the postmortem buffer (cheap, all monitors)
        self._last_blm_wf = {
            el.name: self.synth.blm(float(wpm[k]) if k < len(wpm) else 0.0,
                                    el.params.get("dark_wpm", 1e-3))
            for k, el in enumerate(self.blms)}

        # selected-device live capture
        sel = self.read_hash(keys.settings("wfsel", "main")).get("devices", "")
        names = [n for n in str(sel).split(",") if n][:8]
        if not names:
            return
        data: dict = {"t_ms": t_ms()}
        for name in names:
            if name in self._tor_by_name:
                data[f"{name}:i"] = tor_wf.get(name)
            elif name in self._blm_by_name:
                data[f"{name}:wpm"] = self._last_blm_wf[name]
            elif name in self._bpm_by_name:
                k = self._bpm_by_name[name]
                el = self.bpms[k]
                s_ma = float(tr["bpm_sum"][k])
                nz = el.params.get("noise_um", 10.0)
                data[f"{name}:x"] = self.synth.bpm(float(tr["bpm_x"][k]),
                                                   s_ma, nz)
                data[f"{name}:y"] = self.synth.bpm(float(tr["bpm_y"][k]),
                                                   s_ma, nz)
                data[f"{name}:sum"] = self.synth.toroid(s_ma, 0.01, 0.002)
        data = {k: v for k, v in data.items() if v is not None}
        self.publish_stream("wf.capture", pulse_id, data)

    def _dump_postmortem(self):
        """Freeze the trip pulse's waveforms, like a real postmortem buffer."""
        if not self._last_blm_wf:
            return
        data = {"t_ms": t_ms()}
        data.update({f"blm:{k}": v for k, v in self._last_blm_wf.items()})
        data.update({f"tor:{k}": v for k, v in self._last_tor_wf.items()})
        self.r.set("wf:postmortem", codec.pack(self._last_pid, data))

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
                    req = self.read_hash(f"req:wire:{name}")
                    npts = int(min(max(req.get("points", 64), 8), 256))
                    ppp = int(min(max(req.get("ppp", 1), 1), 20))
                    pos0 = 0.5 * (edges[:-1] + edges[1:])
                    pos = np.linspace(pos0[0], pos0[-1], npts)
                    self._scan = {"name": name, "step": 0, "tick": 0,
                                  "ppp": ppp,
                                  "hx": np.interp(pos, pos0, hx),
                                  "hy": np.interp(pos, pos0, hy),
                                  "pos": pos}
                    break
        if self._scan is None:
            return
        sc = self._scan
        # wire advances one point per ppp pulses; publish the partial scan
        sc["tick"] += 1
        if sc["tick"] % sc["ppp"]:
            return
        sc["step"] = min(sc["step"] + 1, len(sc["pos"]))
        k = sc["step"]
        noise = self.rng.normal(0, 0.01 * max(sc["hx"].max(), 1e-9), k)
        done = 1.0 if k >= len(sc["pos"]) else 0.0
        self.publish_stream("profile.scan", pulse_id, {
            "name": sc["name"], "done": done,
            "pos_mm": sc["pos"][:k],
            "ix": np.maximum(sc["hx"][:k] + noise, 0.0),
            "iy": np.maximum(sc["hy"][:k] + noise, 0.0)})
        if done:
            self._record_rms(sc["name"], sc["pos"], sc["hx"], sc["hy"])
            self.r.delete(f"req:wire:{sc['name']}")
            self._scan = None

    # ------------------------------------------------------- laserwires

    def _lw_scans(self, pulse_id: int, tr: dict):
        """Photodetachment scans: one laser station at a time, in
        parallel with (and independent of) the solid-wire scanner."""
        from pip2va.common.laserwire import LASER_RMS_MM
        if self._lwscan is None:
            for name, s_m in self.lws.items():
                if not self.r.exists(f"req:lw:{name}"):
                    continue
                req = self.read_hash(f"req:lw:{name}")
                npts = int(min(max(req.get("points", 48), 8), 256))
                ppp = int(min(max(req.get("ppp", 1), 1), 20))
                s_arr = tr["s"]
                sx = float(np.interp(s_m, s_arr, tr["sig_x"])) * 1e3
                sy = float(np.interp(s_m, s_arr, tr["sig_y"])) * 1e3
                cx = float(np.interp(s_m, s_arr, tr["cx"])) * 1e3
                cy = float(np.interp(s_m, s_arr, tr["cy"])) * 1e3
                span = 4.0 * max(sx, sy, 0.3)
                pos = np.linspace(-span, span, npts)
                # measured width = beam (+) laser focus in quadrature
                mx = np.sqrt(sx ** 2 + LASER_RMS_MM ** 2)
                my = np.sqrt(sy ** 2 + LASER_RMS_MM ** 2)
                hx = np.exp(-0.5 * ((pos - cx) / mx) ** 2)
                hy = np.exp(-0.5 * ((pos - cy) / my) ** 2)
                self._lwscan = {"name": name, "step": 0, "tick": 0,
                                "ppp": ppp, "pos": pos,
                                "hx": hx, "hy": hy}
                break
        if self._lwscan is None:
            return
        sc = self._lwscan
        sc["tick"] += 1
        if sc["tick"] % sc["ppp"]:
            return
        sc["step"] = min(sc["step"] + 1, len(sc["pos"]))
        k = sc["step"]
        # photodetachment counting statistics (Poisson-like)
        n0 = 4000.0
        ix = self.rng.poisson(np.maximum(sc["hx"][:k] * n0, 0.01)) / n0
        iy = self.rng.poisson(np.maximum(sc["hy"][:k] * n0, 0.01)) / n0
        done = 1.0 if k >= len(sc["pos"]) else 0.0
        self.publish_stream("profile.scan", pulse_id, {
            "name": sc["name"], "done": done,
            "pos_mm": sc["pos"][:k],
            "ix": ix.astype(np.float64), "iy": iy.astype(np.float64)})
        if done:
            self._record_rms(sc["name"], sc["pos"], sc["hx"], sc["hy"])
            self.r.delete(f"req:lw:{sc['name']}")
            self._lwscan = None

    # -------------------------------------------------- profiler cycling

    def _record_rms(self, name, pos, hx, hy):
        if self._cycle is None:
            return
        w = np.maximum(hx, 0)
        mx = np.sum(pos * w) / max(np.sum(w), 1e-9)
        sx = np.sqrt(np.sum(w * (pos - mx) ** 2) / max(np.sum(w), 1e-9))
        w = np.maximum(hy, 0)
        my = np.sum(pos * w) / max(np.sum(w), 1e-9)
        sy = np.sqrt(np.sum(w * (pos - my) ** 2) / max(np.sum(w), 1e-9))
        self._cycle["results"][name] = {
            "sig_x_mm": round(float(sx), 4), "sig_y_mm": round(float(sy), 4)}

    def _profiler_cycle(self, pulse_id: int):
        """Cycle mode: step through every wire scanner one at a time and,
        in parallel, every laserwire station one at a time."""
        st = self.read_hash(keys.settings("profilers", "main"))
        if not st.get("cycle"):
            if self._cycle is not None:
                self._cycle = None
            return
        if self._cycle is None:
            self._cycle = {"ws": list(self.wss), "lw": list(self.lws),
                           "results": {}}
        cy = self._cycle
        ws_pts = int(st.get("ws_points", 64))
        ws_ppp = int(st.get("ws_ppp", 1))
        lw_pts = int(st.get("lw_points", 48))
        lw_ppp = int(st.get("lw_ppp", 1))
        if self._scan is None and cy["ws"]:
            nm = cy["ws"].pop(0)
            self.r.hset(f"req:wire:{nm}", mapping={
                "plane": "x", "points": ws_pts, "ppp": ws_ppp})
        if self._lwscan is None and cy["lw"]:
            nm = cy["lw"].pop(0)
            self.r.hset(f"req:lw:{nm}", mapping={
                "plane": "x", "points": lw_pts, "ppp": lw_ppp})
        n_tot = len(self.wss) + len(self.lws)
        n_done = len(cy["results"]) + (
            n_tot - len(cy["ws"]) - len(cy["lw"])
            - (0 if self._scan is None else 1)
            - (0 if self._lwscan is None else 1) - len(cy["results"]))
        self.r.hset("state:profilers", mapping={
            "status": f"cycling: {len(self.wss)-len(cy['ws'])}/"
                      f"{len(self.wss)} wires, "
                      f"{len(self.lws)-len(cy['lw'])}/{len(self.lws)} "
                      f"lasers", "cycle": 1})
        if not cy["ws"] and not cy["lw"] and self._scan is None \
                and self._lwscan is None:
            import json as _json
            self.r.set("state:profile.summary", _json.dumps({
                "t": __import__("time").time(),
                "stations": cy["results"]}))
            self.r.hset(keys.settings("profilers", "main"), "cycle", 0)
            self.r.hset("state:profilers", mapping={
                "status": f"cycle complete: {len(self.lws)} lasers + "
                          f"{len(self.wss)} wires", "cycle": 0})
            self._cycle = None

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
