n_and_alerts_over_rest():
    s, c = make_client()
    with c:
        z = {"id": "core", "name": "Core", "kind": "circle", "center_lat": SITE.lat, "center_lon": SITE.lon,
             "radius_m": 3000, "level": "critical"}
        assert c.post("/api/v1/zones", json=z).status_code == 201
        assert c.post("/api/v1/zones", json={**z, "radius_m": None}).status_code == 422
        assert [x["id"] for x in c.get("/api/v1/zones").json()] == ["core"]
        c.post("/api/v1/ingest/detections", json=det_stream(s, time.time()))
        alerts = wait_for(lambda: c.get("/api/v1/alerts?active=true").json())
        assert alerts[0]["zone_id"] == s"][0]["status"] == "confirmed"
        ws.send_json({"subscribe": {"classes": ["bird"], "min_confidence": 0.1}})
        end = time.time() + 4
        while time.time() < end:
            msg = ws.receive_json()
            if msg["type"] == "subscribed":
                assert msg["classes"] == ["bird"]
            if msg["type"] == "snapshot" and msg["count"] == 0:
                break
        else:
            raise AssertionError("filtered snapshot never arrived")
        ws.send_json({"subscribe": {"classes": ["not-a-class"]}})
        err = wait_for(lambda: ws.receive_json()["type"] == "error")
        assert err


@pytest.mark.parametrize("n", [1])
def test_udp_and_tcp_ingest_end_to_end_with_latency_budget(n):
    s, c = make_client(udp=True)
    with c:
        rt = c.app.state.runtime
        pipe: Pipeline = c.app.state.pipeline
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        now = time.time()
        stream = det_stream(s, now, n=8)
        sock.sendto(json.dumps(stream[:4]).encode(), ("127.0.0.1", rt.udp.port))  # JSON array datagram
        for d in stream[4:6]:
            sock.sendto(json.dumps(d).encode(), ("127.0.0.1", rt.udp.port))  # single-object datagram
        with socket.create_connection(("127.0.0.1", rt.tcp.port)) as tcp:
            tcp.sendall(("\n".join(json.dumps(d) for d in stream[6:]) + "\nnot json\n").encode())
        wait_for(lambda: pipe.stats["received"] >= 8)
        assert pipe.stats["rejected_malformed"] >= 1
        t = wait_for(lambda: c.get("/api/v1/tracks").json())[0]
        assert t["status"] == "confirmed"
        lat = pipe.metrics()["latency_ms"]
        assert lat["p99"] < 500.0, lat  # ingest -> tracked, well inside the 500 ms display budget
