"""Physics dashboard: every model parameter, visible and live-tunable.

Writes go to settings:physics:main; beam-physics folds them into the engine
each pulse. Live readouts show what the models are currently producing.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtWidgets import (QDoubleSpinBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QTextEdit,
                             QVBoxLayout)

from .. import theme
from . import register
from .common import Page

_MODEL_DOC = """
<h3>What this simulator models — follow the beam</h3>

<p><b>Engines.</b> Two coupled beam models run continuously. The
<b>envelope engine</b> (<code>physics/envelope.py</code>) is the per-pulse
core: it propagates the 6-D beam <i>moments</i> (the 6×6 σ-matrix — RMS
sizes, divergences, energy spread and their correlations) element-by-element
through the lattice at 20 Hz, giving orbit, sizes, transmission, loss power,
emittance and dp/p. A free-running <b>GPU macro-particle tracker</b>
(<code>physics/macro.py</code>, ~10⁵ particles on CuPy) tracks the full phase
-space every few seconds for the 3-D cloud, halo and per-station emittance.</p>

<p><b>① Ion source &amp; LEBT (30 keV).</b> A DC H⁻ beam, space-charge
dominated, transported by solenoids. The source current and emittance seed
the whole simulation; the low-energy space charge sets the initial size.</p>

<p><b>② RFQ (→2.1 MeV, 162.5 MHz).</b> Bunches the DC beam and accelerates
it — modelled as the matched transform to a bunched 2.1 MeV output.</p>

<p><b>③ MEBT.</b> Matching quadrupoles, the <b>chopper</b> (builds the bunch
pattern and the Booster extraction-kicker notch), and buncher cavities that
set the longitudinal match into the SC linac.</p>

<p><b>④ SC linac — HWR → SSR1 → SSR2 → LB650 → HB650 (→800 MeV).</b>
Superconducting <b>RF cavities</b> accelerate; each is a live
<b>cavity model</b> (<code>rf_sim</code>) with Lorentz-force detuning,
He-pressure / piezo microphonics, forward power and quench. <b>Solenoids and
quadrupoles</b> focus (magnet model, with as-built field errors). H⁻-specific
losses — <b>intrabeam</b> and <b>residual-gas stripping</b> — plus a
3-D-ellipsoid <b>space-charge</b> kick are folded in every step.</p>

<p><b>⑤ BTL transfer line.</b> <b>Debunchers</b> rotate the longitudinal
phase space to squeeze dp/p; two achromatic arcs and collimators steer the
800 MeV beam to the stripping foil.</p>

<p><b>⑥ Booster injection.</b> Foil stripping, multi-turn painting, and the
space-charge tune shift set the figure of merit (see the Booster Injection
page). Everything downstream — losses, orbit, RF, emittance — is measured by
<b>diag-sim</b>, which turns ground truth into noisy instrument readings.</p>

<p><i>The parameters below are the knobs into these models — change one and
the beam-physics engine folds it in on the next pulse.</i></p>
"""

# (field, label, default, min, max, decimals, description)
PARAMS = {
    "Space charge": [
        ("sc_scale", "SC strength ×", 1.0, 0.0, 5.0, 2,
         "scales the 3D-ellipsoid space-charge kick (0 = off)"),
        ("sc_form_factor", "Ellipsoid form factor ×", 1.0, 0.0, 2.0, 2,
         "scales longitudinal/transverse SC partition f(p)"),
    ],
    "H⁻ losses": [
        ("ibst_scale", "Intrabeam stripping ×", 1.0, 0.0, 10.0, 2,
         "Lebedev IBSt: σ_max = 4e-19 m², ∝ N/(γ²σxσyσz)"),
        ("gas_scale", "Gas stripping ×", 1.0, 0.0, 10.0, 2,
         "residual-gas: σ = 1e-19/β² cm²/atom"),
        ("pressure_torr", "Vacuum pressure [Torr]", 1e-8, 1e-10, 1e-6, 10,
         "H₂-equivalent pressure seen by the beam"),
    ],
    "Optics": [
        ("disp_scale", "BTL residual dispersion ×", 0.1, 0.0, 1.0, 2,
         "arc achromat closure quality (1 = fully open dispersion)"),
    ],
    "Beam input": [
        ("src:current_ma", "Source current [mA]", 5.0, 0.0, 15.0, 2,
         "pre-chop H⁻ current from the ion source"),
        ("chop:duty", "Chopper keep-fraction", 0.4, 0.0, 1.0, 2,
         "fraction of bunches kept by the MEBT chopper"),
    ],
}


@register("Physics")
class PhysicsPage(Page):
    title = "Physics Model — Parameters & Live State"

    def build(self):
        doc = QTextEdit()
        doc.setReadOnly(True)
        doc.setHtml(_MODEL_DOC)
        doc.setMinimumHeight(260)
        self.body.addWidget(doc)

        grid = QGridLayout()
        self._spins = {}
        live = self.hub.get_settings("physics", "main")
        col = 0
        for gi, (group, items) in enumerate(PARAMS.items()):
            box = QGroupBox(group)
            form = QGridLayout(box)
            for r, (field, label, dflt, lo, hi, dec, tip) in enumerate(items):
                lab = QLabel(label)
                lab.setToolTip(tip)
                sp = QDoubleSpinBox()
                sp.setRange(lo, hi)
                sp.setDecimals(dec)
                sp.setSingleStep(10 ** (-min(dec, 2)))
                sp.setValue(float(live.get(field, dflt))
                            if not field.startswith(("src:", "chop:"))
                            else self._special_get(field, dflt))
                sp.setToolTip(tip)
                sp.valueChanged.connect(
                    lambda v, f=field: self._write(f, v))
                desc = QLabel(tip)
                desc.setStyleSheet("color:#8b96a5; font-size:10px;")
                desc.setWordWrap(True)
                form.addWidget(lab, r * 2, 0)
                form.addWidget(sp, r * 2, 1)
                form.addWidget(desc, r * 2 + 1, 0, 1, 2)
                self._spins[field] = sp
            grid.addWidget(box, gi // 2, gi % 2)
        self.body.addLayout(grid)

        btn = QPushButton("Reset all to defaults")
        btn.clicked.connect(self._reset)
        self.body.addWidget(btn)

        # live model state
        box = QGroupBox("Live model state")
        lay = QGridLayout(box)
        self._live = {}
        for i, (key, label) in enumerate([
                ("w_out", "Output energy [MeV]"),
                ("transmission", "Transmission"),
                ("lag_ms", "Envelope pass [ms]"),
                ("emit", "εx / εy (macro) [µm]"),
                ("alive", "Macro survival"),
                ("det", "RF detuning rms [Hz]"),
                ("loss", "Worst BLM [W/m]"),
                ("wtof", "TOF energy (last BPM) [MeV]")]):
            lay.addWidget(QLabel(label), i // 4 * 2, i % 4)
            val = QLabel("—")
            val.setStyleSheet(f"color:{theme.ACCENT}; font-weight:bold;")
            lay.addWidget(val, i // 4 * 2 + 1, i % 4)
            self._live[key] = val
        self.body.addWidget(box)
        self.body.addStretch(1)

        self.hub.beamState.connect(self._on_state)
        self.hub.deep.connect(self._on_deep)
        self.hub.rf.connect(self._on_rf)
        self.hub.losses.connect(self._on_losses)
        self.hub.orbit.connect(self._on_orbit)

    def _special_get(self, field, dflt):
        cls, f = ("source", "current_ma") if field.startswith("src:") \
            else ("chopper", "duty")
        return float(self.hub.get_settings(cls, "main").get(f, dflt))

    def _write(self, field, v):
        if field == "src:current_ma":
            self.hub.set_setting("source", "main", "current_ma", v)
        elif field == "chop:duty":
            self.hub.set_setting("chopper", "main", "duty", v)
        else:
            self.hub.set_setting("physics", "main", field, v)

    def _reset(self):
        for group in PARAMS.values():
            for field, _l, dflt, *_ in group:
                self._spins[field].setValue(dflt)

    # ------------------------------------------------------------- live

    def _on_state(self, st):
        if not st or not self.isVisible():
            return
        self._live["w_out"].setText(f"{st.get('w_out', 0):.1f}")
        self._live["transmission"].setText(f"{st.get('transmission', 0):.4f}")
        self._live["lag_ms"].setText(f"{st.get('lag_ms', 0):.1f}")

    def _on_deep(self, _p, d):
        if not self.isVisible():
            return
        if len(d.get("emit_x_um", [])):
            self._live["emit"].setText(
                f'{d["emit_x_um"][-1]:.2f} / {d["emit_y_um"][-1]:.2f}')
        self._live["alive"].setText(f'{d.get("alive_frac", 0):.4f}')

    def _on_rf(self, _p, d):
        if self.isVisible():
            self._live["det"].setText(
                f'{float(np.std(d["detuning_hz"])):.1f}')

    def _on_losses(self, _p, d):
        if self.isVisible() and len(d["wpm"]):
            self._live["loss"].setText(f'{float(np.max(d["wpm"])):.3f}')

    def _on_orbit(self, _p, d):
        if self.isVisible() and len(d.get("w_tof", [])):
            self._live["wtof"].setText(f'{float(d["w_tof"][-1]):.1f}')
