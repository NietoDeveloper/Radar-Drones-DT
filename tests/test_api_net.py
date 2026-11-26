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