import jsoetenv("SDT_RADAR_API_KEY", "from-env")
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
