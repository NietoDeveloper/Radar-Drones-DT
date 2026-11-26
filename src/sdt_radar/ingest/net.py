"""Network ingestion: UDP datagrams and TCP line streams carrying JSON detections.

Wire format (one of):

* a JSON object                       -> one detection
* a JSON array of objects             -> a batch
* newline-delimited JSON (TCP / UDP)  -> one detection per line


from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
            if not line:
                continue
            try:
                objs.append(json.loads(line))
            except json.JSONDecodeError:
                pipeline.stats["rejected_malformed"] += 1
    for o in objs:
        if pipeline.ingest_raw(o):
            accepted += 1
    return accepted


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) > MAX_DATAGRAM:
            self.pipeline.stats["rejected_malformed"] += 1
            return
        parse_payload(data, self.pipeline)

    def error_received(self, exc: Exception) -> None:  # pragma: no cover - OS dependent
        log.warning("udp error: %s", exc)


class UdpIngest:
    def __init__(self, pipeline: Pipeline, host: str, port: int) -> None:
        self.pipeline, self.host, self.port = pipeline, host, port
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> int:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self.pipeline), local_addr=(self.host, self.port))
        self.port = self._transport.get_extra_info("sockname")[1]
        return self.port

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None


class TcpIngest:
    def __init__(self, pipeline: Pipeline, host: str, port: int) -> None:
        self.pipeline, self.host, self.port = pipeline, host, port
        self._server: asyncio.Server | None = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, self.host, self.port, limit=MAX_LINE)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
          s