"""``sdt-radar`` command line: serve, simulate, replay, score, benchmark, radar sizing."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.request
from typing import Any

from . import __version__
from .config import load_settings


def _http_json(method: str, url: str, body: Any, api_key: str | None) -> Any:
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", **({"x-api-key": api_key} if api_key else {})})
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - operator-supplied URL
        return json.loads(r.read() or b"null")


def _scenario(name: str, seed: int, duration: float | None, targets: int):
    from .sim import perimeter_scenario, swarm_scenario

    if name == "perimeter":
        return perimeter_scenario(seed=seed, duration_s=duration or 150.0)
    return swarm_scenario(n_targets=targets, seed=seed, duration_s=duration or 60.0)


# ---------------------------------------------------------------------------------- commands
def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app
    from .logsetup import configure_logging

    settings = load_settings(a.config)
    if a.host:
        settings.api.host = a.host
    if a.port:
        settings.api.port = a.port
    if a.tls_cert:
        settings.api.tls_certfile, settings.api.tls_keyfile = a.tls_cert, a.tls_key
    configure_logging(settings.logging.format, settings.logging.level)
    api = settings.api
    loopback = api.host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not (api.keys or api.api_key):
        print("refusing to expose the API without authentication: add [[api.keys]] (sdt-radar keygen) "
              "or set SDT_RADAR_API_KEY", file=sys.stderr)
        return 2
    if not loopback and not api.tls_certfile:
        print("warning: serving without TLS on a non-loopback address — terminate TLS in a reverse proxy "
              "or pass --tls-cert/--tls-key", file=sys.stderr)
    if bool(api.tls_certfile) != bool(api.tls_keyfile):
        print("--tls-cert and --tls-key must be given together", file=sys.stderr)
        return 2
    uvicorn.run(create_app(settings), host=api.host, port=api.port, log_config=None, server_header=False,
                ssl_certfile=api.tls_certfile, ssl_keyfile=api.tls_keyfile)
    return 0


def cmd_keygen(a: argparse.Namespace) -> int:
    from .security import Role, generate_key

    token, rec = generate_key(Role.parse(a.role), a.id)
    print("API key (shown ONCE — store it in your secret manager; it cannot be recovered):\n")
    print(f"  {token}\n")
    print("Add this to the server configuration (only the hash is stored):\n")
    print(f'[[api.keys]]\nid = "{rec["id"]}"\nrole = "{rec["role"]}"\nsha256 = "{rec["sha256"]}"')
    return 0


def cmd_audit_verify(a: argparse.Namespace) -> int:
    from .security import AuditLog

    rep = AuditLog.verify(a.path)
    if rep.ok:
        print(f"OK: {rep.records} records, hash chain intact")
        return 0
    print(f"TAMPERED: line {rep.error_line}: {rep.error} (verified {rep.records} records before it)", file=sys.stderr)
    return 1


def cmd_forward(a: argparse.Namespace) -> int:
    import asyncio
    import contextlib
    import os

    from .forwarder import Forwarder, serve_forward
    from .logsetup import configure_logging

    configure_logging("text", "INFO")
    secrets: dict[str, bytes] = {}
    for spec in a.sign or []:
        sid, _, env = spec.partition("=")
        if not sid or not os.environ.get(env):
            print(f"--sign {spec}: environment variable {env!r} is empty or missing", file=sys.stderr)
            return 2
        secrets[sid] = os.environ[env].strip().encode()
    key = os.environ.get(a.api_key_env) if a.api_key_env else None
    if a.api_key_env and not key:
        print(f"environment variable {a.api_key_env!r} is empty or missing", file=sys.stderr)
        return 2
    fwd = Forwarder(a.hub, key, batch_size=a.batch_size, secrets=secrets, cafile=a.cafile)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve_forward(fwd, a.host, a.listen_udp, a.listen_tcp))
    print(json.dumps(fwd.stats))
    return 0


def cmd_sim(a: argparse.Namespace) -> int:
    from .ingest.recorder import JsonlRecorder
    from .sim import generate

    scn = _scenario(a.scenario, a.seed, a.duration, a.targets)
    if a.api:
        for s in scn.sensor_configs():
            _http_json("POST", f"{a.api}/api/v1/sensors", s.model_dump(mode="json"), a.api_key)
        for z in scn.zones:
            _http_json("POST", f"{a.api}/api/v1/zones", z.model_dump(mode="json"), a.api_key)
        print(f"registered {len(scn.sensor_configs())} sensors and {len(scn.zones)} zones on {a.api}")
    dets = generate(scn)
    print(f"{scn.name}: {len(scn.targets)} targets, {len(dets)} detections over {scn.duration_s:.0f}s")
    if a.out:
        rec = JsonlRecorder(a.out)
        for d in dets:
            rec.write(d)
        rec.close()
        print(f"wrote {a.out}")
    if a.udp:
        host, port = a.udp.rsplit(":", 1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        offset = time.time() - scn.t0_epoch  # shift the scenario so it plays "now"
        wall0, t_first = time.monotonic(), dets[0].t
        batch: list[dict[str, Any]] = []
        size = 0

        def flush() -> None:
            nonlocal batch, size
            if batch:
                sock.sendto(json.dumps(batch).encode(), (host, int(port)))
                batch, size = [], 0

        for d in dets:
            delay = (d.t - t_first) / a.speed - (time.monotonic() - wall0)
            if delay > 0:
                flush()
                time.sleep(delay)
            item = d.model_copy(update={"t": d.t + offset}).model_dump(mode="json", exclude_none=True)
            enc = len(json.dumps(item))
            if size + enc > 60_000:
                flush()
            batch.append(item)
            size += enc
        flush()
        print("done")
    return 0


def cmd_replay(a: argparse.Namespace) -> int:
    from .ingest import read_jsonl, replay
    from .pipeline import Pipeline

    settings = load_settings(a.config)
    pipe = Pipeline(settings)
    pipe.start()
    res = replay(read_jsonl(a.file), pipe, realtime=a.realtime, speed=a.speed)
    print(json.dumps({"processed": res.measurements, "created": res.created, "confirmed": res.confirmed,
                      "alerts": len(res.alerts), "metrics": pipe.metrics()}, indent=2, default=str))
    pipe.close()
    return 0


def cmd_score(a: argparse.Namespace) -> int:
    from .sim import run_scenario

    scn = _scenario(a.scenario, a.seed, a.duration, a.targets)
    pipe, score, alerts = run_scenario(scn)
    print(json.dumps({"scenario": scn.name, "targets": len(scn.targets),
                      "score": {k: (round(v, 3) if v == v else None) for k, v in score.summary().items()},
                      "alerts_raised": len(alerts), "tracker": pipe.tracker.stats}, indent=2))
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    from . import bench

    print(json.dumps(bench.run(a.targets, a.duration or 60.0, a.seed), indent=2))
    return 0


def cmd_train(_: argparse.Namespace) -> int:
    from .classification.train import main as train_main

    train_main()
    return 0


def cmd_budget(a: argparse.Namespace) -> int:
    from .radar import radar_range_m, range_resolution_m, velocity_resolution_mps

    r = radar_range_m(a.power_w, a.gain_dbi, a.freq_ghz * 1e9, a.rcs_m2, a.snr_db, a.bandwidth_mhz * 1e6,
                      a.nf_db, a.loss_db, a.integration_db)
    print(f"max detection range ({a.rcs_m2} m² at SNR>={a.snr_db} dB): {r:,.0f} m")
    print(f"range resolution: {range_resolution_m(a.bandwidth_mhz * 1e6):.2f} m")
    print(f"velocity resolution (50 ms dwell): {velocity_resolution_mps(a.freq_ghz * 1e9, 0.05):.2f} m/s")
    return 0


def cmd_catalog(_: argparse.Namespace) -> int:
    from .radar import RADAR_CATALOG

    for c in RADAR_CATALOG:
        print(f"{c.key:22s} {c.name}")
        print(f"  range km: {c.typical_range_km}\n  +: {c.strengths}\n  -: {c.weaknesses}\n  use: {c.best_for}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdt-radar", description="SoftwareDT drone-radar backend")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the API + ingestion servers")
    s.add_argument("--config")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--tls-cert", help="PEM certificate (enables HTTPS/WSS)")
    s.add_argument("--tls-key", help="PEM private key")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("keygen", help="create an API key (prints the token once and the hash to store)")
    s.add_argument("--role", choices=["viewer", "operator", "admin"], default="viewer")
    s.add_argument("--id", help="public key id (default: random)")
    s.set_defaults(fn=cmd_keygen)

    s = sub.add_parser("audit-verify", help="verify the hash chain of an audit log")
    s.add_argument("path")
    s.set_defaults(fn=cmd_audit_verify)

    s = sub.add_parser("forward", help="edge node: collect detections locally and forward them to a hub")
    s.add_argument("--hub", required=True, help="hub base URL, e.g. https://radar-hub:8080")
    s.add_argument("--api-key-env", help="environment variable holding an operator-role API key")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--listen-udp", type=int, default=9100)
    s.add_argument("--listen-tcp", type=int, default=9101)
    s.add_argument("--sign", action="append", metavar="SENSOR=ENVVAR", help="sign this sensor's detections (repeatable)")
    s.add_argument("--batch-size", type=int, default=200)
    s.add_argument("--cafile", help="CA bundle (PEM) to verify the hub certificate (private CA / self-signed)")
    s.set_defaults(fn=cmd_forward)

    def scenario_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--scenario", choices=["perimeter", "swarm"], default="perimeter")
        sp.add_argument("--seed", type=int, default=1)
        sp.add_argument("--duration", type=float)
        sp.add_argument("--targets", type=int, default=300, help="swarm size")

    s = sub.add_parser("sim", help="generate a synthetic scenario; stream it over UDP and/or save as JSONL")
    scenario_args(s)
    s.add_argument("--udp", help="host:port of a running server's UDP ingest, e.g. 127.0.0.1:9100")
    s.add_argument("--api", help="base URL to register the scenario's sensors/zones, e.g. http://127.0.0.1:8080")
    s.add_argument("--api-key")
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--out", help="write detections as JSON lines (for replay)")
    s.set_defaults(fn=cmd_sim)

    s = sub.add_parser("replay", help="replay a recorded JSONL file offline")
    s.add_argument("file")
    s.add_argument("--config")
    s.add_argument("--realtime", action="store_true")
    s.add_argument("--speed", type=float, default=1.0)
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("score", help="run a scenario offline and print tracking metrics")
    scenario_args(s)
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("bench", help="scale benchmark (default 500 simultaneous targets)")
    s.add_argument("--targets", type=int, default=500)
    s.add_argument("--duration", type=float)
    s.add_argument("--seed", type=int, default=2)
    s.set_defaults(fn=cmd_bench)

    sub.add_parser("train-classifier", help="retrain the packaged synthetic micro-Doppler model").set_defaults(fn=cmd_train)
    sub.add_parser("catalog", help="print the sensor-type catalogue").set_defaults(fn=cmd_catalog)

    s = sub.add_parser("budget", help="radar range equation / resolution calculator")
    s.add_argument("--power-w", type=float, default=1.0)
    s.add_argument("--gain-dbi", type=float, default=25.0)
    s.add_argument("--freq-ghz", type=float, default=10.0)
    s.add_argument("--rcs-m2", type=float, default=0.01)
    s.add_argument("--snr-db", type=float, default=13.0)
    s.add_argument("--bandwidth-mhz", type=float, default=50.0)
    s.add_argument("--nf-db", type=float, default=5.0)
    s.add_argument("--loss-db", type=float, default=4.0)
    s.add_argument("--integration-db", type=float, default=20.0)
    s.set_defaults(fn=cmd_budget)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
