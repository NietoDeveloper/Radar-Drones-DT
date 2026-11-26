n_and_alerts_over_rest():
    s, c = make_client()
    with c:
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
