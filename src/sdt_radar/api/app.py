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
    async def zors() -> list[dict[sidence": sub.min_confidence, "include_tentative": sub.include_tentative})
                except (ValueError, TypeError, AttributeError) as exc:
                    sub.push({"type": "error", "detail": str(exc)})
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            hub.remove(sub)

    return app
