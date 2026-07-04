"""Redis key and pub/sub channel naming — the single vocabulary shared by all
services and the GUI. Never build a key with raw f-strings elsewhere."""

# Pub/sub channels
CH_TICK = "pulse.tick"          # timing service heartbeat: {"pulse_id", "t"}
CH_SETTINGS = "settings.changed"  # payload: settings hash key that changed
CH_MPS = "mps.trip"             # beam permit dropped
CH_FAULT = "device.fault"       # payload: readback hash key of faulted device


def stream(product: str) -> str:
    """Stream carrying one msgpack entry per pulse for a data product."""
    return f"stream:{product}"


def settings(cls: str, name: str) -> str:
    """Operator-written setpoint hash for a device (cls: magnet|rf|source|chopper|mps)."""
    return f"settings:{cls}:{name}"


def readback(cls: str, name: str) -> str:
    """Simulated device readback hash (what beam-physics and the GUI read)."""
    return f"readback:{cls}:{name}"


def truth(name: str) -> str:
    """Ground-truth beam state. Internal to the backend; the GUI never reads it."""
    return f"truth:{name}"


def fault(cls: str, name: str) -> str:
    """Fault-injection request hash for a device."""
    return f"fault:{cls}:{name}"


def heartbeat(service: str) -> str:
    """Service liveness key (SET with TTL by each service)."""
    return f"hb:{service}"
