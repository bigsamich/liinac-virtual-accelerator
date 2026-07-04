"""Settings audit trail: every setpoint write lands in stream:settings.log.

This is the machine's "who touched what, when" record — the first thing the
fault analysis reads after a trip.
"""
from __future__ import annotations

import time

SETTINGS_LOG = "stream:settings.log"


def log_setting(r, key: str, field: str, value, source: str):
    r.xadd(SETTINGS_LOG,
           {"t": time.time(), "key": key, "field": field,
            "value": str(value), "source": source},
           maxlen=2000, approximate=True)


def read_log(r, n: int = 100) -> list[dict]:
    out = []
    for _, fields in r.xrevrange(SETTINGS_LOG, count=n):
        out.append({(k.decode() if isinstance(k, bytes) else k):
                    (v.decode() if isinstance(v, bytes) else v)
                    for k, v in fields.items()})
    return out
