import jsoetenv("SDT_RADAR_API_KEY", "from-env")
    s = load_settings(p)
    assert s.tracker.confirm_hits == 5 and s.sensors[0].id == "a" and s.api.api_key == "from-env"
    with pytest.raises(Exception):  # noqa: B017
        Settings.model_validate({"tracker": {"coast_after_s": 5, "max_coast_s": 2}})  # inconsistent
    with pytest.raises(Exc