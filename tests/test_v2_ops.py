import asyncio
import json
import logging
import time

import numpy as np
import pytest

from sdt_radar.cli import main
from sdt_radar.config import Settings
from sdt_radar.logsetup import JsonFormatter, request_id
from sdt_radar.models import TrackPoint
from sdt_radar.pipeline import Pipeline
from sdt_radar.runtime import Runtime
from sdt_radar.security import ApiKeyStore, AuditLog, Role
from sdt_radar.sim import generate, perimeter_scenario
from tests.helpers import settings_for


def test_keygen_prints_a_working_token_and_only_the_hash_for_config(capsys):
    assert main(["keygen", "--role", "operator", "--id", "edge-7"]) == 0
    out = capsys.readouterr().out
    token = next(line.strip() for line in out.splitlines() if line.strip().startswith("sdtr_edge-7_"))
    sha = next(line.split('"')[1] for line in out.splitlines() if line.startswith("sha256"))
    assert 'role = "operator"' in out and 'id = "edge-7"' in out and token not in out.split("[[api.keys]]")[1]
    store = ApiKeyStore([("edge-7", Role.operator, sha)])
    assert store.verify(token).role == Role.operator
    cfg = Settings.model_validate({"api": {"keys": [{"id": "edge-7", "role": "operator", "sha256": sha}]}})
    assert cfg.api.keys[0].role == "operator"


def test_audit_verify_cli_exit_codes(tmp_path, capsys):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    for i in range(4):
        log.append("zone_create", detail={"i": i}, ts=100.0 + i)
    assert main(["audit-verify", str(p)]) == 0 and "4 records" in capsys.readouterr().out
    p.write_text(p.read_text().replace('"i":1', '"i":7'))
    assert main(["audit-verify", str(p)]) == 1 and "TAMPERED" in capsys.readouterr().err


def test_forward_command_refuses_missing_secrets(capsys, monkeypatch):
    monkeypatch.delenv("SDT_NO_SUCH", raising=False)
    assert main(["forward", "--hub", "http://127.0.0.1:1", "--sign", "edge-1=SDT_NO_SUCH"]) == 2
    assert main(["forward", "--hub", "http://127.0.0.1:1", "--api-key-env", "SDT_NO_SUCH"]) == 2


@pytest.mark.parametrize("bad", [
    {"api": {"keys": [{"id": "a", "role": "viewer", "sha256": "0" * 64}, {"id": "a", "role": "admin", "sha256": "1" * 64}]}},
    {"api": {"keys": [{"id": "a", "role": "root", "sha256": "0" * 64}]}},
    {"api": {"keys": [{"id": "a b", "role": "viewer", "sha256": "0" * 64}]}},
    {"api": {"keys": [{"id": "a", "role": "viewer", "sha256": "xyz"}]}},
    {"api": {"tls_certfile": "c.pem"}},
    {"notify": {"webhooks": [{"url": "ftp://nope"}]}},
    {"tracker": {"imm_sigma_h_mps2": [1.0, 2.0], "imm_sigma_v_mps2": [1.0]}},
    {"ingest": {"max_clock_skew_s": 0}},
])
def test_unsafe_or_inconsistent_v2_configuration_is_rejected(bad):
    with pytest.raises(Exception):  # noqa: B017
        Settings.model_validate(bad)


def test_json_logs_carry_the_request_id():
    rec = logging.LogRecord("sdt_radar.test", logging.WARNING, __file__, 1, "something %s", ("odd",), None)
    token = request_id.set("req-123456789")
    try:
        row = json.loads(JsonFormatter().format(rec))
    finally:
        request_id.reset(token)
    assert row["msg"] == "something odd" and row["level"] == "WARNING" and row["request_id"] == "req-123456789"


async def test_retention_task_prunes_old_points_and_audits_it(tmp_path):
    s = settings_for(storage={"kind": "memory", "retention_days": 1.0}, audit={"enabled": True, "path": str(tmp_path / "a.jsonl")},
                     ingest={"udp_port": None, "tcp_port": None})
    pipe = Pipeline(s)
    pipe.start()
    now = time.time()

    def pt(t):
        return TrackPoint(t=t, lat=1, lon=1, alt_m=1, vel_e_mps=0, vel_n_mps=0, vel_u_mps=0, speed_mps=0, heading_deg=0,
                          position_sigma_m=1, confidence=1, sensors=[])

    pipe.store.write_points("t1", [pt(now - 3 * 86400), pt(now - 2 * 86400), pt(now - 60)])
    rt = Runtime(pipe, s, hub=__import__("sdt_radar.api.hub", fromlist=["StreamHub"]).StreamHub(5.0))
    task = asyncio.create_task(rt._retention())
    for _ in range(50):
        await asyncio.sleep(0.05)
        if pipe.stats["retention_pruned"]:
            break
    task.cancel()
    assert pipe.stats["retention_pruned"] == 2 and len(pipe.store.history("t1")) == 1
    assert [r["action"] for r in pipe.audit.tail()] == ["retention_prune"]


def test_perimeter_scenario_includes_range_less_bearing_detections():
    scn = perimeter_scenario(seed=2, duration_s=20)
    dets = generate(scn)
    eo = [d for d in dets if d.sensor_id == "eo-1"]
    assert eo and all(d.range_m is None and d.azimuth_deg is not None and d.geometry == "angular" for d in eo)
    assert not any(d.range_m is None for d in dets if d.sensor_id != "eo-1" and d.lat is None)
    assert perimeter_scenario(seed=2, duration_s=20, with_eo=False).bearings == []
    assert np.isfinite([d.t for d in dets]).all()
