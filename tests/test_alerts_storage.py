import numpy as np
import pytest

from sdt_radar.alerts import AlertEngine
from sdt_radar.config import AlertConfig
from sdt_radar.models import AlertLevel, AlertType, TargetClass, TrackOut, TrackStatus, Zone
from sdt_radar.storage import MemoryStore, SqliteStore
from sdt_radar.tracking.track import Track
from tests.helpers import FRAME, SITE


def mk_track(pos, vel=(0, 0, 0), status=TrackStatus.confirmed, cls=None, conf_n=6, seq=1):
    x = np.array([*pos, *vel], float)
    tr = Track(seq=seq, x=x, P=np.eye(6), t=100.0, first_t=90.0, last_hit_t=100.0, hits=10, status=status)
    if cls is not None:
        probs = np.array([0.9, 0.05, 0.05]) if cls == TargetClass.drone else np.array([0.03, 0.94, 0.03])
        for _ in range(conf_n):
            tr.klass.update(probs, 0.95)
    return tr


def test_circle_polygon_and_altitude_band_containment():
    eng = AlertEngine(FRAME, [circle(300, min_alt_m=2600, max_alt_m=2800)], AlertConfig())
    zi = eng.zones["z1"]
    assert zi.contains(np.array([100.0, 100.0, 0.0]), 2700.0)
    assert not zi.contains(np.array([400.0, 0.0, 0.0]), 2700.0)  # outside radius
    assert not zi.contains(np.array([0.0, 0.0, 0.0]), 3500.0)  # above altitude band
    pts = [FRAME.to_geodetic(np.array([e, n, 0.0])) for e, n in [(-200, -200), (200, -200), (200, 200), (-200, 200)]]
    poly = Zone(id="p", name="Poly", kind="polygon", polygon=[(float(a), float(b)) for a, b, _ in pts])
    zp = AlertEngine(FRAME, [poly], AlertConfig()).zones["p"]
    assert zp.contains_xy(0, 0) and zp.contains_xy(190, -190) and not zp.contains_xy(250, 0)


def test_intrusion_opens_once_escalates_and_closes_with_hysteresis():
    eng = AlertEngine(FRAME, [circle(300)], AlertConfig(clear_after_s=5.0, lookahead_s=0))
    inside = mk_track([50, 50, 100], cls=TargetClass.drone)
    ev = eng.evaluate([inside], 100.0)
    assert len(ev) == 1 and ev[0].type == AlertType.zone_intrusion and ev[0].state == "open" and ev[0].risk > 0.9
    assert eng.evaluate([inside], 101.0) == []  # no spam while nothing changes
    inside.x[:3] = [900, 0, 100]  # left the zone
    assert eng.evaluate([inside], 103.0) == []  # still within hysteresis
    ev = eng.evaluate([inside], 107.0)
    assert len(ev) == 1 and ev[0].state == "closed" and ev[0].closed_at == 107.0


def test_approach_alert_uses_extrapolation_and_cancels_when_heading_away():
    eng = AlertEngine(FRAME, [circle(300)], AlertConfig(lookahead_s=30.0, clear_after_s=2.0))
    tr = mk_track([800, 0, 100], vel=(-20, 0, 0), cls=TargetClass.drone)  # enters in ~25 s
    ev = eng.evaluate([tr], 100.0)
    assert ev and ev[0].type == AlertType.zone_approach and ev[0].level == AlertLevel.warning and "~2" in ev[0].message
    tr.x[3:] = [20, 0, 0]
    ev = eng.evaluate([tr], 101.0)
    assert ev and ev[0].state == "closed"


def test_birds_are_suppressed_unknowns_are_not_and_tentative_never_alert():
    eng = AlertEngine(FRAME, [circle(300)], AlertConfig(lookahead_s=0))
    bird = mk_track([10, 10, 50], cls=TargetClass.bird, seq=1)
    unknown = mk_track([20, 20, 50], seq=2)
    tent = mk_track([30, 30, 50], status=TrackStatus.tentative, seq=3)
    ev = eng.evaluate([bird, unknown, tent], 100.0)
    assert [e.track_id for e in ev] == [unknown.track_id]
    assert ev[0].target_class == TargetClass.unknown and 0.5 < ev[0].risk < 0.7


def test_lost_track_closes_its_alerts_and_zone_management():
    eng = AlertEngine(FRAME, [circle(300)], AlertConfig(lookahead_s=0))
    tr = mk_track([10, 10, 50], cls=TargetClass.drone)
    eng.evaluate([tr], 100.0)
    closed = eng.close_for_track(tr.track_id, 101.0)
    assert len(closed) == 1 and closed[0].state == "closed" and not eng.open_alerts()
    assert eng.remove_zone("z1") and not eng.remove_zone("z1") and eng.evaluate([tr], 102.0) == []


# ------------------------------------------------------------------------------- storage
def _track_out(tid="t1", status=TrackStatus.confirmed, last=100.0, cls=TargetClass.drone):
    return TrackOut(track_id=tid, seq=1, status=status, target_class=cls, class_confidence=0.9, confidence=0.8,
                    lat=4.7, lon=-74.0, alt_m=2700, east_m=1, north_m=2, up_m=3, vel_e_mps=1, vel_n_mps=0,
                    vel_u_mps=0, speed_mps=1, heading_deg=90, climb_mps=0, rcs_dbsm=-20, position_sigma_m=5,
                    sensors=["r1"], first_seen=90.0, last_seen=last, age_s=10, hits=9)


def _point(t):
    from sdt_radar.models import TrackPoint
    return TrackPoint(t=t, lat=4.7, lon=-74.0, alt_m=2700, vel_e_mps=1, vel_n_mps=0, vel_u_mps=0, speed_mps=1,
                      heading_deg=90, position_sigma_m=5, confidence=0.8, sensors=["r1"])


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    s = MemoryStore() if request.param == "memory" else SqliteStore(tmp_path / "radar.db")
    s.start()
    yield s
    s.close()


def test_store_tracks_points_alerts_zones_and_prune(store):
    from sdt_radar.models import AlertOut
    store.write_track(_track_out("a", last=100)); store.write_track(_track_out("b", TrackStatus.lost, 50, TargetClass.bird))
    store.write_track(_track_out("a", last=120))  # upsert
    store.write_points("a", [_point(t) for t in (10, 20, 30, 40)])
    al = AlertOut(alert_id="x1", type=AlertType.zone_intrusion, level=AlertLevel.critical, state="open", track_id="a",
                  zone_id="z", zone_name="Z", opened_at=1, updated_at=2, closed_at=None, risk=0.9,
                  target_class=TargetClass.drone, message="m", lat=1, lon=1, alt_m=1)
    store.write_alert(al); store.write_alert(al.model_copy(update={"state": "closed", "updated_at": 3, "closed_at": 3}))
    store.put_zone(circle()); store.put_zone(circle(500)); store.flush()
    assert store.get_track("a").last_seen == 120 and store.get_track("nope") is None
    assert [t.track_id for t in store.list_tracks()] == ["a", "b"]  # newest first
    assert [t.track_id for t in store.list_tracks(target_class=TargetClass.bird)] == ["b"]
    assert [t.track_id for t in store.list_tracks(status=TrackStatus.lost)] == ["b"]
    assert [p.t for p in store.history("a")] == [10, 20, 30, 40]
    assert [p.t for p in store.history("a", since=20, until=30)] == [20, 30]
    assert [a.state for a in store.list_alerts()] == ["closed"] and store.list_alerts(active_only=True) == []
    assert [z.radius_m for z in store.list_zones()] == [500]
    assert store.prune(25) == 2 and [p.t for p in store.history("a")] == [30, 40]
    store.delete_zone("z1"); store.flush()
    assert store.list_zones() == []


def test_sqlite_survives_restart_and_batches_writes(tmp_path):
    path = tmp_path / "sub" / "radar.db"
    s = SqliteStore(path); s.start()
    for i in range(500):
        s.write_points("a", [_point(float(i))])
    s.write_track(_track_out("a")); s.close()  # close() must drain the queue
    s2 = SqliteStore(path); s2.start()
    assert len(s2.history("a")) == 500 and s2.get_track("a") is not None
    s2.close()
