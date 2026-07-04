"""Snapshot save / diff / restore."""
import fakeredis

from pip2va.common import keys, snapshots
from pip2va.services.magnet_sim.main import MagnetSimService
from pip2va.services.rf_sim.main import RfSimService


def test_snapshot_roundtrip(tmp_path):
    r = fakeredis.FakeStrictRedis()
    MagnetSimService(redis_client=r).on_start()
    RfSimService(redis_client=r).on_start()

    p = snapshots.save(r, "golden", note="test", directory=tmp_path)
    assert p.exists()
    lst = snapshots.list_snapshots(directory=tmp_path)
    assert lst[0]["name"] == "golden" and lst[0]["n"] > 200

    # no drift yet: empty diff
    snap = snapshots.load("golden", directory=tmp_path)
    assert snapshots.diff(r, snap) == []

    # operator "fat-fingers" two settings
    r.hset(keys.settings("magnet", "SSR2:SOL5"), "current", 999.0)
    r.hset(keys.settings("rf", "HWR:CAV3"), "phase", 55.0)
    d = snapshots.diff(r, snap)
    assert {(e["key"], e["field"]) for e in d} == {
        (keys.settings("magnet", "SSR2:SOL5"), "current"),
        (keys.settings("rf", "HWR:CAV3"), "phase")}

    # restore puts them back
    n = snapshots.restore(r, snap)
    assert n > 200
    assert snapshots.diff(r, snap) == []
    # audit trail shows the restore
    from pip2va.common import audit
    assert any(e["source"].startswith("restore:")
               for e in audit.read_log(r, 5))
