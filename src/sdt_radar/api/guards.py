"""ASGI middlewares: security headers, request-size limit, request id. Pure ASGI (no buffering)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from starlette.types import Message, Receive, Scope, Send

from ..logsetup import request_id

_RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class SecurityHeaders:
    """Adds hardening headers; HSTS only when the service itself terminates TLS."""

    def __init__(self, app: Any, hsts: bool = False) -> None:
        self.app, self.hsts = app, hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def wrapped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                h = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"server"]
                h += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                      (b"referrer-policy", b"no-referrer"), (b"cross-origin-resource-policy", b"same-origin")]
                if path.startswith("/api") or path == "/health" or path == "/metrics":
                    h += [(b"cache-control", b"no-store"),
                          (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")]
                if self.hsts:
                    h.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = h
            await send(message)

        await self.app(scope, receive, wrapped)


class BodyLimit:
    """Reject request bodies larger than ``max_bytes`` (declared or streamed) with 413."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app, self.max = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max:
            await self._reject(send)
            return
        seen = 0
        rejected = False

        async def limited() -> Message:
            nonlocal seen, rejected
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max:
                    rejected = True
                    return {"type": "http.disconnect"}
            return msg

        started = False

        async def guarded_send(message: dict[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            if not rejected or started is False:
                await send(message)

        await self.app(scope, limited, guarded_send)
        if rejected and not started:
            await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"detail":"request body too large"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class RequestId:
    """Accept a well-formed ``X-Request-ID`` or mint one; echo it and expose it to the logger."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _RID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id.set(rid)

        async def wrapped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            request_id.reset(token)
