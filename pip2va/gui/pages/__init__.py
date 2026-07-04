"""GUI page registry: nav label -> page class (filled in as pages land).

Each page class takes (hub, lattice) and is a QWidget.
"""
PAGES: dict[str, type] = {}


def register(label: str):
    def deco(cls):
        PAGES[label] = cls
        return cls
    return deco


def load_all():
    """Import all page modules so they self-register."""
    import importlib
    for mod in ("overview", "orbit", "losses", "magnets", "rf", "profiles",
                "waveforms", "striptool", "snapshots_page", "source", "mps"):
        try:
            importlib.import_module(f"{__name__}.{mod}")
        except ImportError:
            pass  # page not built yet
    return PAGES
