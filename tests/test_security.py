import json
import time

import pytest

from sdt_radar.models import Detection
from sdt_radar.pipeline import Pipeline
from sdt_radar.security import (
    ApiKeyStore,
    AuditLog,
    AuthLockout,
    RateLimiter,
    ReplayCache,
    Role,
    TicketStore,
    generate_key,
    load_secret,
    sign,
    verify,
)
from tests.helpers import sensor_cfg, settings_for

# ------------------------------------------------------------------------------------------ keys


def test_api_keys_roles_hashing_and_constant_time_paths():
    tok_v, rec_v = generate_key(Role.viewer)
    tok_a, rec_a = generate_key(Role.admin, "ops-1")
    assert set(rec_v) == {"id", "role", "sha256"} and tok_v not in json.dumps(rec_v)  # only the hash is stored
    store = ApiKeyStore([(rec_v["id"], Role.viewer, rec_v["sha256"]), ("ops-1", Role.admin, rec_a["sha256"])])
    pv, pa = store.verify(tok_v), store.verify(tok_a)
    assert pv and pv.role == Role.viewer and pa and pa.key_id == "ops-1"
    assert pa.allows(Role.operator) and pa.allows(Role.viewer) and not pv.allows(Role.operator)  # hierarchy
    secret = tok_v.split("_", 2)[2]
    assert store.verify(tok_v[:-1] + ("A" if tok_v[-1] != "A" else "B")) is None  # wrong secret
    assert store.verify(f"sdtr_nobody_{secret}") is None  # unknown id
    assert store.verify(None) is None and store.verify("") is None and store.verify("garbage") is None
    with pytest.raises(ValueError):
        generate_key(Role.viewer, "bad_id")
    with pytest.raises(ValueError):
        Role.parse("root")


def test_legacy_single_key_maps_to_admin():
    store = ApiKeyStore([], legacy_admin_key="s3cret")
    assert store.enabled and store.verify("s3cret").role == Role.admin and store.verify("nope") is None
    assert not ApiKeyStore([]).enabled


# --------------------------------------------------------------------------------- rate limiting


def test_token_bucket_burst_refill_and_bounded_memory():
    rl = RateLimiter(rate_per_s=2.0, burst=3.0, max_keys=5)
    assert [rl.allow("a", 0.0)[0] for _ in range(4)] == [True, True, True, False]
    ok, retry = rl.allow("a", 0.0)
    assert not ok and retry == pytest.approx(0.5)
    assert rl.allow("a", 1.0)[0]  # refilled 2 tokens after 1 s
    for i in range(50):
        rl.allow(f"k{i}", 0.0)
    assert len(rl._b) <= 5  # key-spraying cannot grow memory


def test_lockout_after_repeated_failures_and_reset_on_success():
    lk = AuthLockout(max_failures=3, window_s=10, lock_s=60)
    assert not lk.failure("1.2.3.4", 0) and not lk.failure("1.2.3.4", 1)
    lk.success("1.2.3.4")
    assert not lk.failure("1.2.3.4", 2) and not lk.failure("1.2.3.4", 3)
    assert lk.failure("1.2.3.4", 4) and lk.locked("1.2.3.4", 5) == pytest.approx(59)
    assert lk.locked("5.6.7.8", 5) == 0 and lk.locked("1.2.3.4", 100) == 0  # per client; expires
    lk2 = AuthLockout(max_failures=3, window_s=10, lock_s=60)
    lk2.failure("x", 0); lk2.failure("x", 1)
    assert not lk2.failure("x", 20)  # old failures fall out of the window


# ------------------------------------------------------------------------------------- signing


def test_signature_is_order_independent_tamper_evident_and_ignores_none():
    secret = b"k" * 32
    det = {"sensor_id": "r1", "t": 1795000000.5, "range_m": 1200.5, "azimuth_deg": 10.0, "elevation_deg": 2.0}
    sig = sign(secret, det)
    assert verify(secret, {**det, "sig": sig})
    assert verify(secret, {"elevation_deg": 2.0, "azimuth_deg": 10.0, "t": 1795000000.5, "range_m": 1200.5,
                           "sensor_id": "r1", "sig": sig, "rcs_dbsm": None})  # key order / None fields irrelevant
    assert not verify(secret, {**det, "range_m": 1200.6, "sig": sig})  # any change breaks it
    assert not verify(b"other-secret", {**det, "sig": sig})
    assert not verify(secret, det) and not verify(secret, {**det, "sig": 5})
    assert not verify(secret, {**det, "t": float("nan"), "sig": sig})  # NaN cannot be canonicalised


def test_replay_cache_ttl_and_secret_loading(tmp_path, monkeypatch):
    rc = ReplayCache(ttl_s=10)
    assert not rc.seen("a", 0) and rc.seen("a", 5) and not rc.seen("a", 20)
    monkeypatch.setenv("SDT_TEST_SECRET", " from-env \n")
    f = tmp_path / "secret"
    f.write_text("from-file\n")
    assert load_secret("SDT_TEST_SECRET", None) == b"from-env"
    assert load_secret(None, str(f)) == b"from-file"
    assert load_secret("MISSING_VAR", None) is None


def test_ws_tickets_are_single_use_and_expire():
    ts = TicketStore(ttl_s=10)
    _, rec = generate_key(Role.viewer)
    p = ApiKeyStore([(rec["id"], Role.viewer, rec["sha256"])])
    principal = p.verify(generate_key(Role.viewer)[0]) or __import__("sdt_radar.security", fromlist=["Principal"]).Principal("k", Role.viewer)
    t = ts.issue(principal, 0.0)
    assert ts.redeem(t, 1.0) == principal and ts.redeem(t, 1.0) is None  # single use
    t2 = ts.issue(principal, 0.0)
    assert ts.redeem(t2, 11.0) is None and ts.redeem(None, 0) is None  # expired / absent


# ------------------------------------------------------------------------------------- audit


def test_audit_chain_detects_edit_delete_reorder_and_survives_restart(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(5):
        log.append("zone_create", actor="k1", role="operator", ip="10.0.0.1", detail={"zone": i}, ts=1000.0 + i)
    assert AuditLog.verify(path).ok and AuditLog.verify(path).records == 5
    head = log.head()
    assert AuditLog(path).head() == head  # a restarted process continues the same chain
    AuditLog(path).append("zone_delete", ts=2000.0)
    lines = path.read_text().splitlines()
    assert AuditLog.verify(path).records == 6

    def tampered(new_lines):
        p = tmp_path / "t.jsonl"
        p.write_text("\n".join(new_lines) + "\n")
        return AuditLog.verify(p)

    edited = list(lines)
    edited[2] = edited[2].replace('"zone":2', '"zone":99')
    rep = tampered(edited)
    assert not rep.ok and rep.error_line == 3 and "altered" in rep.error
    rep = tampered(lines[:2] + lines[3:])  # deleted record
    assert not rep.ok and rep.error_line == 3
    rep = tampered([lines[1], lines[0], *lines[2:]])  # reordered
    assert not rep.ok and rep.error_line == 1
    with pytest.raises(ValueError):
        (tmp_path / "bad.jsonl").write_text(edited and "\n".join(edited) + "\n")
        AuditLog(tmp_path / "bad.jsonl")  # refuses to append to a corrupted log


def test_audit_flood_is_capped_per_action(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", max_per_min=3)
    results = [log.append("auth_failure", ts=100.0 + i * 0.1) for i in range(10)]
    assert results.count(True) == 3 and log.suppressed == 7
    assert log.append("auth_failure", ts=200.0)  # window passed
    assert log.append("other_action", ts=100.0)  # other actions have their own budget


# ----------------------------------------------------------------- pipeline signature policy


def det_dict(sensor, **kw):
    d = {"sensor_id": sensor.id, "t": time.time(), "range_m": 1500.0, "azimuth_deg": 40.0, "elevation_deg": 3.0}
    d.update(kw)
    return d


def test_signed_sensor_policy_unsigned_forged_replayed_and_skewed(monkeypatch, tmp_path):
    monkeypatch.setenv("SDT_S1_SECRET", "s" * 32)
    s1 = sensor_cfg("signed-1", hmac_secret_env="SDT_S1_SECRET")
    s2 = sensor_cfg("plain-1")
    pipe = Pipeline(settings_for(s1, s2, audit={"enabled": True, "path": str(tmp_path / "audit.jsonl")}))
    pipe.start()
    secret = b"s" * 32
    good = det_dict(s1)
    good["sig"] = sign(secret, good)
    assert pipe.ingest_raw(good)
    assert not pipe.ingest_raw(good) and pipe.stats["rejected_replay"] == 1  # same signature again
    assert not pipe.ingest_raw(det_dict(s1)) and pipe.stats["rejected_unsigned"] == 1
    forged = det_dict(s1, range_m=999.0)
    forged["sig"] = sign(b"wrong-secret", forged)
    assert not pipe.ingest_raw(forged) and pipe.stats["rejected_bad_signature"] == 1
    old = det_dict(s1, t=time.time() - 3600)
    old["sig"] = sign(secret, old)
    assert not pipe.ingest_raw(old) and pipe.stats["rejected_skew"] == 1  # captured long ago, replayed late
    assert pipe.ingest_raw(det_dict(s2))  # unsigned sensor is fine when signatures are not globally required
    actions = [r["detail"]["reason"] for r in pipe.audit.tail() if r["action"] == "ingest_rejected"]
    assert {"signature already used", "signature required", "signature mismatch"} <= set(actions)
    assert AuditLog.verify(tmp_path / "audit.jsonl").ok


def test_require_signatures_globally_and_fail_closed_on_missing_secret(monkeypatch):
    s = sensor_cfg("plain-1")
    pipe = Pipeline(settings_for(s, ingest={"require_signatures": True, "udp_port": None, "tcp_port": None}))
    assert not pipe.ingest_raw(det_dict(s)) and pipe.stats["rejected_unsigned"] == 1  # no secret configured
    monkeypatch.delenv("SDT_NOPE", raising=False)
    with pytest.raises(ValueError, match="signing secret not found"):
        Pipeline(settings_for(sensor_cfg("x", hmac_secret_env="SDT_NOPE")))  # never silently unsigned


def test_per_sensor_network_rate_limit_and_malformed_input_never_crash():
    s = sensor_cfg("r1", rate_limit_per_s=5.0)
    pipe = Pipeline(settings_for(s))
    ok = sum(pipe.ingest_raw(det_dict(s)) for _ in range(40))
    assert 8 <= ok <= 14 and pipe.stats["rejected_rate"] >= 26  # burst of 2x the rate, then throttled
    for junk in (b"\x00\xff", "[1,2", 42, None, {"sensor_id": 5}, {"sensor_id": "r1", "t": "now"}, [], "null"):
        assert pipe.ingest_raw(junk) is False
    assert isinstance(Detection.model_validate(det_dict(s)), Detection)
