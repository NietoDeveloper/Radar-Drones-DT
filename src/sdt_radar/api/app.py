"""FastAPI application: REST + WebSocket for dashboards and other Software DT backends."""

from __future__ import annotations

import asyncio
import hmac
import time
from contextlib import asynccontextmanager
from typing import Annotated, AnyertOut], tags=["alerts"])
    async def alerts(active: bool = False, since: float | None = None,
                     limit: Annotated[int, Query(ge=1, le=5000)] = 1000) -> list[AlertOut]:
        if active:
            return pipe.alerts.open_alerts()[:limit]
        return await asyncio.to_thread(pipe.store.list_alerts, False, since, limit)

    @api.get("/zones", response_model=list[Zone], tags=["zones"])
    async def zors() -> list[dict[str, Any]]:
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
