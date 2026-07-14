"""Commit-horizon input injection — how interactivity stays deterministic.

Operators and agents fire setpoint changes at arbitrary wall-clock moments, but
a deterministic core can only accept them at frame boundaries. So every command
that "arrives" during pulse N is scheduled to apply at pulse ``N + horizon`` and
recorded in the event log. The horizon is an input-latency budget (exactly the
rollback-netcode / GGPO trick): it's what lets "interactive" and "replayable"
coexist — the outcome depends only on *which pulse* a command lands at, never on
the wall-clock jitter of when it arrived.
"""
from __future__ import annotations

from .eventlog import EventLog


class InputInjector:
    def __init__(self, driver, log: EventLog | None = None,
                 horizon: int | None = None):
        self.driver = driver
        self.log = log or EventLog()
        self.horizon = (horizon if horizon is not None
                        else driver.settings.commit_horizon)

    def submit(self, setpoints: dict) -> int:
        """A command arriving 'now' -> deterministically applied at
        ``current pulse + horizon``. Returns the target pulse."""
        target = self.driver.pulse_id + max(1, self.horizon)
        self.log.append(target, "setpoint", setpoints)
        return target

    def _apply_due(self):
        nxt = self.driver.pulse_id + 1
        due = self.log.inputs_by_pulse().get(nxt)
        if due:
            self.driver.apply(due)

    def step(self, beam_on: bool = True) -> dict:
        self._apply_due()
        return self.driver.step(beam_on=beam_on)

    def run(self, n_pulses: int) -> list[dict]:
        return [self.step() for _ in range(n_pulses)]
