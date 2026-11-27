"""FastAPI application: REST + WebSocket for dashboards and other Software DT backends."""

from __future__ import annotations

import asyncio
import hmac
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
def create_app(settings: Settings | None = None, *, pipeline: Pipeline | None = None,
               run_runtime: bool = True) -> FastAPI:
    settings = settings or load_settings()
-----------------------------------

    @api.get("/tracks/{track_id}", response_model=TrackOut, tags=["tracks"])
    async def track(track_id: str) -> TrackOut:
        live = pipe.live_track(track_id)
        if live is not None:
            return live
        archived = await asyncio.to_thread(pipe.store.get_track, track_id)
        if archived is None:
            raise HTTPException(404, "unknown track")
        return archived

    @api.get("/tracks/{track_id}/history", response_model=list[TrackPoint], tags=["tracks"])
    async def history(track_id: str, since: float | None = None, until: float | None = None,
                      limit: Annotated[int, Query(ge=1, le=20000)] = 5000) -> list[TrackPoint]:
        pts = await asyncio.to_thread(pipe.store.history, track_id, since, until, limit)
        if not pts:
            live = pipe.live_history(track_id)
            if live is None and await asyncio.to_thread(pipe.store.get_track, track_id) is None:
                raise HTTPException(404, "unknown track")
            pts = [p for p in (live or []) if (since is None or p.t >= since) and (until is None or p.t <= until)][:limit]
        return pts

    @api.get("/archive/tracks", response_model=list[TrackOut], tags=["archive"])
    async def archive(status: TrackStatus | None = None, target_class: TargetClass | None = None,
                      since: float | None = None, limit: Annotated[int, Query(ge=1, le=5000)] = 1000) -> list[TrackOut]:
        return await asyncio.to_thread(pipe.store.list_tracks, status, target_class, since, limit)

    @api.get("/alerts", response_model=list[AlertOut], tags=["alerts"])
    async def alerts(active: bool = False, since: float | None = None,
                     limit: Annotated[int, Query(ge=1, le=5000)] = 1000) -> list[AlertOut]:
        if active:
            return pipe.alerts.open_alerts()[:limit]
        return await asyncio.to_thread(pipe.store.list_alerts, False, since, limit)

    @api.get("/zones", response_model=list[Zone], tags=["zones"])
    async def zones() -> list[Zone]:
        return pipe.alerts.list_zones()

    @api.post("/zones", response_model=Zone, status_code=201, tags=["zones"])
    async def add_zone(zone: Zone) -> Zone:
        pipe.add_zone(zone)
        return zone

    @api.delete("/zones/{zone_id}", status_code=204, tags=["zones"])
    async def delete_zone(zone_id: str) -> None:
        if not pipe.remove_zone(zone_id):
            raise HTTPException(404, "unknown zone")

    @api.get("/sensors", tags=["sensors"])
    async def sensors() -> list[dict[str, Any]]:
        now = time.time()
        out = []
        for sid, cfg in pipe.factory.sensors.items():
            st = pipe.sensor_state.get(sid)
            out.append({**cfg.model_dump(mode="json"),
                        "detections": int(st["count"]) if st else 0,
                        "last_seen_age_s": round(now - st["last_rx"], 2) if st and st["last_rx"] else None})
        return out

    @api.post("/sensors", response_model=SensorConfig, status_code=201, tags=["sensors"])
    async def register_sensor(sensor: SensorConfig) -> SensorConfig:
        pipe.register_sensor(sensor)
        return sensor

    @api.post("/ingest/detections", tags=["ingest"])
    async def ingest(batch: list[dict[str, Any]]) -> dict[str, int]:
        if len(batch) > MAX_INGEST_BATCH:
            raise HTTPException(413, f"batch too large (max {MAX_INGEST_BATCH})")
        ok = sum(1 for d in batch if pipe.ingest_raw(d))
        return {"accepted": ok, "rejected": len(batch) - ok}

    app.include_router(api)

    # ------------------------------------------------------------------------------ websocket
    @app.websocket("/ws/v1/stream")
    async def stream(ws: WebSocket, api_key: str | None = None) -> None:
        if not _key_ok(api_key or ws.headers.get("x-api-key")):
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
                    cfg = msg.get("subscribe", {})
                    if "classes" in cfg:
                        sub.classes = {TargetClass(c) for c in cfg["classes"]} or None
                    if "min_confidence" in cfg:
                        sub.min_confidence = min(max(float(cfg["min_confidence"]), 0.0), 1.0)
                    if "include_tentative" in cfg:
                        sub.include_tentative = bool(cfg["include_tentative"])
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
