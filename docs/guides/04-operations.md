# 04 — Operations: Studies, Training, Snapshots, MPS

## Studies (the heart of the program)
**Plan & Run tab**
- Quick chips: one-press validated plans (FF fade, dead-cavity drill,
  dispersion, drift soak) and AI-prompt templates (phase acceptance,
  intensity ramp, steering survey, aperture probe).
- **Natural language → Plan**: describe the study ("sweep SSR1:CAV11
  phase ±5°, 9 steps, restore after"); the AI planner uses the
  knowledge base to pick safe spans; the JSON plan is editable.
- Presets dropdown: the standing measurement library, each tagged with
  what it teaches.
- **Queue** (shared machine-wide — desktop, phone, scripts all see it),
  Run next, auto-run, Abort (issues RESCUE).
- Plan options: `steps`, `dwell_s`, `restore`, `autotune` (orbit trim
  during dwells — use for optics studies, never steering studies),
  `rebaseline` (re-baseline MPS at each plateau — intensity ramps),
  `capture_orbit`, `capture_rf_wf`, `pre` (settings applied before,
  restored after).
- The executor survives everything: settle after arming, errant-event
  retry, marginal-trip auto-rebaseline, reset→relearn escalation.
  155+ consecutive unattended studies without a trip.

**Previous studies tab**: every result file, rule-based report, AI
re-analysis, "Load plan → editor" for next-generation studies, and the
live knowledge base view (what feeds the AI).

## Training
15 scenarios in three tiers (★ easy / ★★ medium / ★★★ hard): cavity
trips, quenches, chopper misconfigurations, drifting solenoids,
corrector runaways, sabotaged settings, double faults, silent detunes.
Completion = permit restored + faults cleared + transmission > 99% +
settings back within 5%. Post-run **review** reconstructs what was
injected vs what you did (from the audit trail); **AI debrief** grades
and coaches.

## Snapshots
SCORE-style save/compare/restore of every setpoint. `golden` is the
known-good state RESCUE restores; it carries a lattice fingerprint so a
stale golden after a lattice change is refused. Save a new golden after
any deliberate improvement (steering campaigns do this automatically).

## MPS
Thresholds = max(energy-scaled activation base, learned mean+8σ,
3×mean). **Relearn** re-captures baselines (required after intensity /
steering / pattern changes; auto-EMA tracks slow drift, capped at 5×
base). Event log, trip analysis (rule-based + LLM root-cause naming
devices and s-positions), and the fault injector (device faults with
magnitudes/units — drive training or tests). Permit reset also lives on
the banner, always.
