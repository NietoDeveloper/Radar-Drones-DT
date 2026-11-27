"""FastAPI application: REST + WebSocket for dashboards and other Software DT backends.

Security model (see docs/SECURITY.md): hashed API keys with hierarchical roles (viewer < operator < admin),
per-IP rate limiting and brute-force lockout, short-lived single-use WebSocket tickets, hardening
headers, request-size limits, optional Host allow-list, and a tamper-evident audit log of every
security-relevant action. When no keys are configured the API is open — acceptable on loopback only
(the CLI refuses to bind elsewhere without keys).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__
from ..config import Settings, load_settings
from ..models import AlertOut, SensorConfig, TargetClass, TrackOut, TrackPoint, TrackStatus, Zone
from ..notify import WebhookNotifier
from ..pipeline import Pipeline
from ..runtime import Runtime
from ..security import ApiKeyStore, AuthLockout, Principal, RateLimiter, Role, TicketStore
from .guards import BodyLimit, RequestId, SecurityHeaders
from .hub import PROTOCOL_VERSION, StreamHub
from .prom import render as render_prometheus

MAX_INGEST_BATCH = 5000


def create_app(settings: Settings | None = None, *, pipeline: Pipeline | None = None,
               run_runtime: bool = True) -> FastAPI:
    settings = settings or load_settings()
    cfg = settings.api
    pipe = pipeline or Pipeline(settings)
    hub = StreamHub(cfg.snapshot_hz)
    notifier = WebhookNotifier(settings.notify.webhooks) if settings.notify.webhooks else None
    runtime = Runtime(pipe, settings, hub, notifier)
    started = time.time()

    keys = ApiKeyStore([(k.id, Role.parse(k.role), k.sha256) for k in cfg.keys], cfg.api_key)
    limiter = RateLimiter(cfg.rate_limit_per_s, cfg.rate_limit_burst)
    lockout = AuthLockout(cfg.lockout_failures, cfg.lockout_window_s, cfg.lockout_s)
    tickets = TicketStore(cfg.ws_ticket_ttl_s)
    audit = pipe.audit

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipe.start()
        if run_runtime:
            await runtime.start()
        yield
        if run_runtime:
            await runtime.stop()
        pipe.close()

    app = FastAPI(title="SoftwareDT Drone Radar API", version=__version__, lifespan=lifespan)
    app.state.pipeline, app.state.hub, app.state.runtime, app.state.keys = pipe, hub, runtime, keys

    # ---- middleware (outermost last): request id → hardening headers → body limit → host check → CORS
    if cfg.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["GET", "POST", "DELETE"],
                           allow_headers=["x-api-key", "content-type", "x-request-id"])
    if cfg.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=cfg.allowed_hosts)
    app.add_middleware(BodyLimit, max_bytes=cfg.max_body_bytes)
    app.add_middleware(SecurityHeaders, hsts=bool(cfg.tls_certfile))
    app.add_middleware(RequestId)

    # --------------------------------------------------------------------------- auth
    def client_ip(conn: Request | WebSocket) -> str:
        if cfg.trust_proxy_headers:
            fwd = conn.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        return conn.client.host if conn.client else "unknown"

    def audit_event(action: str, ip: str, principal: Principal | None, **detail: Any) -> None:
        if audit is not None:
            audit.append(action, actor=principal.key_id if principal else "-",
                         role=principal.role.name if principal else None, ip=ip, detail=detail)

    def need(role: Role) -> Callable[[Request], Awaitable[Principal]]:
        async def dep(request: Request) -> Principal:
            ip, now = client_ip(request), time.time()
            wait = lockout.locked(ip, now)
            if wait:
                raise HTTPException(429, "too many failed authentications", headers={"Retry-After": str(int(wait) + 1)})
            ok, retry = limiter.allow(ip, now)
            if not ok:
                raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(retry) + 1)})
            if not keys.enabled:
                principal = Principal("anonymous", Role.admin)  # open mode: loopback development only
            else:
                verified = keys.verify(request.headers.get("x-api-key"))
                if verified is None:
                    locked = lockout.failure(ip, now)
                    audit_event("auth_failure", ip, None, path=request.url.path, locked=locked)
                    raise HTTPException(401, "invalid or missing API key")
                principal = verified
                lockout.success(ip)
            if not principal.allows(role):
                audit_event("forbidden", ip, principal, path=request.url.path, needed=role.name)
                raise HTTPException(403, f"requires role '{role.name}'")
            request.state.principal = principal
            return principal

        return dep

    viewer, operator, admin = need(Role.viewer), need(Role.operator), need(Role.admin)

    # -------------------------------------------------------------------------- open
    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        m = pipe.metrics()
        return {"status": "ok", "version": __version__, "uptime_s": round(time.time() - started, 1),
                "tracks": sum(m["tracks_by_status"].values()), "sensors": len(pipe.factory.sensors),
                "ws_clients": len(hub.subscribers)}

    def ws_stats() -> dict[str, int]:
        return {"clients": len(hub.subscribers), "published": hub.published,
                "dropped": sum(s.dropped for s in hub.subscribers)}

    async def prom_auth(request: Request) -> None:
        if not cfg.metrics_public:
            await viewer(request)

    @app.get("/metrics", response_class=PlainTextResponse, tags=["system"], dependencies=[Depends(prom_auth)])
    async def prometheus() -> Response:
        text = render_prometheus(pipe.metrics(), ws_stats(), started, audit.suppressed if audit else 0,
                                 notifier.stats if notifier else None)
        return PlainTextResponse(text, media_type="text/plain; version=0.0.4; charset=utf-8")

    # ---------------------------------------------------------------------- /api/v1
    api = APIRouter(prefix="/api/v1")

    @api.get("/auth/whoami", tags=["auth"])
    async def whoami(p: Principal = Depends(viewer)) -> dict[str, str]:
        return {"key_id": p.key_id, "role": p.role.name}

    @api.post("/auth/ws-ticket", tags=["auth"])
    async def ws_ticket(p: Principal = Depends(viewer)) -> dict[str, Any]:
        return {"ticket": tickets.issue(p, time.time()), "expires_in_s": cfg.ws_ticket_ttl_s}

    @api.get("/metrics", tags=["system"], dependencies=[Depends(viewer)])
    async def metrics() -> dict[str, Any]:
        out = pipe.metrics()
        out["ws"] = ws_stats()
        if notifier:
            out["webhooks"] = dict(notifier.stats)
        return out

    @api.get("/tracks", response_model=list[TrackOut], tags=["tracks"], dependencies=[Depends(viewer)])
    async def tracks(target_class: TargetClass | None = None, status: TrackStatus | None = None,
                     min_confidence: Annotated[float, Query(ge=0, le=1)] = 0.0, include_tentative: bool = False,
                     limit: Annotated[int, Query(ge=1, le=5000)] = 1000) -> list[TrackOut]:
        rows = pipe.snapshot(include_tentative=include_tentative)
        rows = [t for t in rows if (target_class is None or t.target_class == target_class)
                and (status is None or t.status == status) and t.confidence >= min_confidence]
        return rows[:limit]

    @api.get("/tracks/{track_id}", response_model=TrackOut, tags=["tracks"], dependencies=[Depends(viewer)])
    async def track(track_id: str) -> TrackOut:
        live = pipe.live_track(track_id)
        if live is not None:
            return live
        archived = await asyncio.to_thread(pipe.store.get_track, track_id)
        if archived is None:
            raise HTTPException(404, "unknown track")
        return archived

    @api.get("/tracks/{track_id}/history", response_model=list[TrackPoint], tags=["tracks"],
             dependencies=[Depends(viewer)])
    async def history(track_id: str, since: float | None = None, until: float | None = None,
                      limit: Annotated[int, Query(ge=1, le=20000)] = 5000) -> list[TrackPoint]:
        pts = await asyncio.to_thread(pipe.store.history, track_id, since, until, limit)
        if not pts:
            live = pipe.live_history(track_id)
            if live is None and await asyncio.to_thread(pipe.store.get_track, track_id) is None:
                raise HTTPException(404, "unknown track")
            pts = [p for p in (live or []) if (since is None or p.t >= since) and (until is None or p.t <= until)][:limit]
        return pts

    @api.get("/archive/tracks", response_model=list[TrackOut], tags=["archive"], dependencies=[Depends(viewer)])
    async def archive(status: TrackStatus | None = None, target_class: TargetClass | None = None,
                      since: float | None = None, limit: Annotated[int, Query(ge=1, le=5000)] = 1000) -> list[TrackOut]:
        return await asyncio.to_thread(pipe.store.list_tracks, status, target_class, since, limit)

    @api.get("/alerts", response_model=list[AlertOut], tags=["alerts"], dependencies=[Depends(viewer)])
    async def alerts(active: bool = False, since: float | None = None,
                     limit: Annotated[int, Query(ge=1, le=5000)] = 1000) -> list[AlertOut]:
        if active:
            return pipe.alerts.open_alerts()[:limit]
        return await asyncio.to_thread(pipe.store.list_alerts, False, since, limit)

    @api.get("/zones", response_model=list[Zone], tags=["zones"], dependencies=[Depends(viewer)])
    async def zones() -> list[Zone]:
        return pipe.alerts.list_zones()

    @api.post("/zones", response_model=Zone, status_code=201, tags=["zones"])
    async def add_zone(zone: Zone, request: Request, p: Principal = Depends(operator)) -> Zone:
        pipe.add_zone(zone)
        audit_event("zone_create", client_ip(request), p, zone_id=zone.id, level=zone.level.value)
        return zone

    @api.delete("/zones/{zone_id}", status_code=204, tags=["zones"])
    async def delete_zone(zone_id: str, request: Request, p: Principal = Depends(operator)) -> None:
        if not pipe.remove_zone(zone_id):
            raise HTTPException(404, "unknown zone")
        audit_event("zone_delete", client_ip(request), p, zone_id=zone_id)

    @api.get("/sensors", tags=["sensors"], dependencies=[Depends(viewer)])
    async def sensors() -> list[dict[str, Any]]:
        now = time.time()
        out = []
        for sid, s in pipe.factory.sensors.items():
            st = pipe.sensor_state.get(sid)
            out.append({**s.model_dump(mode="json", exclude={"hmac_secret_env", "hmac_secret_file"}),
                        "signed": sid in pipe._secrets, "detections": int(st["count"]) if st else 0,
                        "last_seen_age_s": round(now - st["last_rx"], 2) if st and st["last_rx"] else None})
        return out

    @api.post("/sensors", status_code=201, tags=["sensors"])
    async def register_sensor(sensor: SensorConfig, request: Request, p: Principal = Depends(admin)) -> dict[str, Any]:
        try:
            pipe.register_sensor(sensor)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        audit_event("sensor_register", client_ip(request), p, sensor_id=sensor.id, kind=sensor.kind.value)
        return sensor.model_dump(mode="json", exclude={"hmac_secret_env", "hmac_secret_file"})

    @api.post("/ingest/detections", tags=["ingest"], dependencies=[Depends(operator)])
    async def ingest(batch: list[dict[str, Any]]) -> dict[str, int]:
        if len(batch) > MAX_INGEST_BATCH:
            raise HTTPException(413, f"batch too large (max {MAX_INGEST_BATCH})")
        ok = sum(1 for d in batch if pipe.ingest_raw(d))
        return {"accepted": ok, "rejected": len(batch) - ok}

    @api.get("/audit", tags=["audit"], dependencies=[Depends(admin)])
    async def audit_tail(limit: Annotated[int, Query(ge=1, le=1000)] = 100) -> list[dict[str, Any]]:
        if audit is None:
            raise HTTPException(404, "audit log disabled")
        return audit.tail(limit)

    @api.get("/audit/head", tags=["audit"], dependencies=[Depends(admin)])
    async def audit_head() -> dict[str, Any]:
        if audit is None:
            raise HTTPException(404, "audit log disabled")
        return audit.head()

    app.include_router(api)

    # --------------------------------------------------------------------- websocket
    @app.websocket("/ws/v1/stream")
    async def stream(ws: WebSocket, ticket: str | None = None, api_key: str | None = None) -> None:
        ip, now = client_ip(ws), time.time()
        if lockout.locked(ip, now) or not limiter.allow(ip, now)[0]:
            await ws.close(code=4429)
            return
        principal: Principal | None = None
        if not keys.enabled:
            principal = Principal("anonymous", Role.admin)
        else:
            principal = tickets.redeem(ticket, now)
            if principal is None:
                supplied = ws.headers.get("x-api-key") or (api_key if cfg.allow_query_api_key else None)
                principal = keys.verify(supplied)
            if principal is None:
                lockout.failure(ip, now)
                audit_event("auth_failure", ip, None, path="/ws/v1/stream")
                await ws.close(code=4401)
                return
        await ws.accept()
        sub = hub.add()

        async def sender() -> None:
            while True:
                await ws.send_json(await sub.queue.get())

        send_task = asyncio.create_task(sender())
        try:
            while True:
                msg = await ws.receive_json()
                try:
                    sc = msg.get("subscribe", {})
                    if "classes" in sc:
                        sub.classes = {TargetClass(c) for c in sc["classes"]} or None
                    if "min_confidence" in sc:
                        sub.min_confidence = min(max(float(sc["min_confidence"]), 0.0), 1.0)
                    if "include_tentative" in sc:
                        sub.include_tentative = bool(sc["include_tentative"])
                    sub.push({"type": "subscribed", "protocol": PROTOCOL_VERSION,
                              "classes": sorted(c.value for c in sub.classes) if sub.classes else None,
                              "min_confidence": sub.min_confidence, "include_tentative": sub.include_tentative})
                except (ValueError, TypeError, AttributeError) as exc:
                    sub.push({"type": "error", "detail": str(exc)})
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            hub.remove(sub)

    return app
