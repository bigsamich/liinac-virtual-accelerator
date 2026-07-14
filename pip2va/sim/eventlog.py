"""Append-only event log — the event-sourcing half of time-travel.

Every input (setpoint write, trip, reset) is a timestamped event keyed by
``(pulse_id, seq)``. Combined with periodic snapshots, any past frame is
reconstructable by ``restore(checkpoint)`` then ``replay(events after it)`` — and
because ordering is a total function of ``(pulse_id, seq)``, replay is
deterministic. The event log is also the golden master: two runs are equal iff
their event logs are equal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(order=True)
class Event:
    pulse_id: int
    seq: int
    kind: str = field(compare=False)
    payload: dict = field(compare=False, default_factory=dict)


class EventLog:
    """Ordered, append-only log with a deterministic (pulse_id, seq) total order."""

    def __init__(self):
        self._events: list[Event] = []
        self._seq = 0

    def append(self, pulse_id: int, kind: str, payload: dict | None = None) -> Event:
        ev = Event(pulse_id, self._seq, kind, dict(payload or {}))
        self._seq += 1
        self._events.append(ev)
        return ev

    def between(self, lo: int, hi: int) -> list[Event]:
        """Events with lo < pulse_id <= hi, in canonical order."""
        return sorted(e for e in self._events if lo < e.pulse_id <= hi)

    def inputs_by_pulse(self, lo: int = -1, hi: int = 1 << 62) -> dict:
        """Collapse setpoint events into {pulse_id: {key: value}} for the driver."""
        out: dict[int, dict] = {}
        for e in self.between(lo, hi):
            if e.kind == "setpoint":
                out.setdefault(e.pulse_id, {}).update(e.payload)
        return out

    def to_json(self) -> str:
        return json.dumps([[e.pulse_id, e.seq, e.kind, e.payload]
                           for e in sorted(self._events)])

    @classmethod
    def from_json(cls, s: str) -> "EventLog":
        log = cls()
        for pid, seq, kind, payload in json.loads(s):
            log._events.append(Event(pid, seq, kind, payload))
            log._seq = max(log._seq, seq + 1)
        return log

    def __len__(self):
        return len(self._events)
