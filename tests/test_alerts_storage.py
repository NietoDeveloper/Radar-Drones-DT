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
    assert eng.remove_zone("z1") and not eng.remove_zone("z1") and eng.evaluate([tr], 102.0) == 