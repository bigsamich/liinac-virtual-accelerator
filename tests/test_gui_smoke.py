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
    # every registered page can be constructed
    for i in range(win.nav.count()):
        win.nav.setCurrentRow(i)
        assert win.stack.currentWidget() is not None
