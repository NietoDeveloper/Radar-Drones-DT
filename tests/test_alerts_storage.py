import numpy as np
import pytest

from sdt_radar.alerts import AlertEngine
from sdt_radar.config import AlertConfig
from sdt_radar.models import AlertLevel, AlertType, TargetClass, TrackOut, TrackStatus, Zone
from sdt_radar.storage import MemoryStore, SqliteStore
from sdt_radar.tracking.track import Track
from tests.helpers import FRAME, SITE
zone_management():
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

