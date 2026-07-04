"""GUI smoke tests (offscreen)."""
import os

import fakeredis
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from pip2va.common import codec, keys  # noqa: E402
from pip2va.gui.datahub import DataHub  # noqa: E402
from pip2va.gui.main import MainWindow  # noqa: E402


@pytest.fixture()
def r():
    return fakeredis.FakeStrictRedis()


def test_datahub_emits_orbit(qtbot, r):
    hub = DataHub(redis_client=r)
    hub.start()
    assert hub.wait_ready(3.0)
    try:
        with qtbot.waitSignal(hub.orbit, timeout=5000) as blocker:
            r.xadd(keys.stream("bpm.orbit"), {"d": codec.pack(7, {
                "x": np.zeros(74, dtype=np.float32),
                "y": np.zeros(74, dtype=np.float32),
                "phase": np.zeros(74, dtype=np.float32),
                "sum": np.full(74, 2.0, dtype=np.float32)})})
        pulse_id, data = blocker.args
        assert pulse_id == 7
        assert data["sum"][0] == pytest.approx(2.0)
    finally:
        hub.stop()


def test_datahub_set_setting_writes_hash(qtbot, r):
    hub = DataHub(redis_client=r)
    hub.set_setting("magnet", "SSR1:C2", "current_x", 1.5)
    assert float(r.hget(keys.settings("magnet", "SSR1:C2"), "current_x")) == 1.5


def test_main_window_constructs_and_navigates(qtbot, r):
    hub = DataHub(redis_client=r)
    win = MainWindow(hub)
    qtbot.addWidget(win)
    # 9 registered pages; section views open from the dashboard strip
    assert win.nav.count() == 12
    win.goto_section("SSR2")
    assert win.stack.currentWidget() is win._section_pages["SSR2"]
    for i in range(win.nav.count()):
        win.nav.setCurrentRow(i)
        assert win.stack.currentWidget() is not None


def test_pages_consume_synthetic_signals(qtbot, r):
    from pip2va.common.lattice import load_lattice
    hub = DataHub(redis_client=r)
    win = MainWindow(hub)
    qtbot.addWidget(win)
    lat = load_lattice()
    for i in range(win.nav.count()):        # build all pages
        win.nav.setCurrentRow(i)

    nbpm = len(lat.instruments("bpm"))
    nblm = len(lat.instruments("blm"))
    ntor = len(lat.instruments("toroid"))
    hub.orbit.emit(1, {"x": np.zeros(nbpm, dtype=np.float32),
                       "y": np.zeros(nbpm, dtype=np.float32),
                       "phase": np.zeros(nbpm, dtype=np.float32),
                       "sum": np.full(nbpm, 2.0, dtype=np.float32)})
    hub.losses.emit(1, {"wpm": np.full(nblm, 0.01, dtype=np.float32)})
    hub.toroids.emit(1, {"i_ma": np.full(ntor, 2.0, dtype=np.float32)})
    hub.beamState.emit({"pulse_id": 1, "w_out": 800.0,
                        "transmission": 0.99, "permit": 1.0})
    hub.mpsEvent.emit({"t": "0", "kind": "trip", "detail": "test"})
    ncav = sum(1 for e in lat.elements if e.type in ("rfgap", "rfq"))
    hub.rf.emit(1, {"amp": np.ones(ncav, dtype=np.float32),
                    "phase": np.zeros(ncav, dtype=np.float32),
                    "detuning_hz": np.zeros(ncav, dtype=np.float32),
                    "status": np.zeros(ncav, dtype=np.float32),
                    "forward_pw": np.ones(ncav, dtype=np.float32)})
    # no exceptions -> pages consumed the signals
