import json

import pytest

from sdt_radar.cli import main
from sdt_radar.config import Settings, load_settings


def test_budget_catalog_and_version(capsys):
    assert main(["budget", "--power-w", "10", "--gain-dbi", "30", "--bandwidth-mhz", "10"]) == 0
    out = capsys.readouterr().out
    assert "max detection range" in out and "range resolution: 14.99 m" in out
    assert main(["catalog"]) == 0 and "radar_fmcw" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
ation_s=40)
    cfg.write_text(_to_toml(scn.settings()))
    capsys.readouterr()
    assert main(["replay", str(out), "--config", str(cfg)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["processed"] > 100 and res["confirmed"] >= 3 and res["metrics"]["counters"]["received"] > 100
    assert main(["score", "--scenario", "swarm", "--targets", "40", "--duration", "40", "--seed", "1"]) == 0
    score = json.loads(capsys.readouterr().out)
    assert score["score"]["detection_rate"] > 0.9


def test_serve_refuses_to_expose_without_api_key(capsys, monkeypatch):
    monkeypatch.delenv("SDT_RADAR_API_KEY", raising=False)
    assert main(["serve", "--host", "0.0.0.0"]) == 2  # noqa: S104
    assert "API key" in capsys.readouterr().err


def test_config_loading_validation_and_env_override(tmp_path, monkeypatch):
    p = tmp_path / "c.toml"
    p.write_text('[site]\nlat = 10.0\nlon = -70.0\n[tracker]\nconfirm_hits = 5\n[[sensors]]\nid = "a"\nkind = "radar_fmcw"\nlat = 10.0\nlon = -70.0\n')
    monkeypatch.setenv("SDT_RADAR_API_KEY", "from-env")
    s = load_settings(p)
    assert s.tracker.confirm_hits == 5 and s.sensors[0].id == "a" and s.api.api_key == "from-env"
    with pytest.raises(Exception):  # noqa: B017
        Settings.model_validate({"tracker": {"coast_after_s": 5, "max_coast_s": 2}})  # inconsistent
    with pytest.raises(Exception):  # noqa: B017
        Settings.model_validate({"unknown_section": {}})  # typos are errors, not silently ignored
    with pytest.raises(Exception):  # noqa: B017
        Settings.model_validate({"sensors": [{"id": "a", "kind": "rf", "lat": 0, "lon": 0}] * 2})  # duplicate ids
    assert load_settings(None).ingest.udp_port == 9100


def _to_toml(s: Settings) -> str:
    out = [f"[site]\nlat = {s.site.lat}\nlon = {s.site.lon}\nalt_m = {s.site.alt_m}\n", '[storage]\nkind = "memory"\n']
    for x in s.sensors:
        out.append("[[sensors]]\n" + "\n".join(
            f'{k} = "{v}"' if isinstance(v, str) else f"{k} = {v}" for k, v in x.model_dump(mode="json", exclude_none=True).items()) + "\n")
    return "\n".join(out)
