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
        return await asyncio.to_thread(
        finally:
            send_task.cancel()
            hub.remove(sub)

    return app
