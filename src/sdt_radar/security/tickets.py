"""Short-lived, single-use WebSocket tickets.

Browsers cannot set headers on a WebSocket handshake, and putting a long-lived API key in the URL leaks
it into proxy and access logs. Instead a client calls ``POST /api/v1/auth/ws-ticket`` (authenticated),
receives a random ticket valid for a few seconds, and connects with ``?ticket=...``.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict

from .keys import Principal


class TicketStore:
    def __init__(self, ttl_s: float = 30.0, max_items: int = 10_000) -> None:
        self.ttl_s, self.max_items = ttl_s, max_items
        self._t: OrderedDict[str, tuple[Principal, float]] = OrderedDict()

    def issue(self, principal: Principal, now: float) -> str:
        self._expire(now)
        ticket = secrets.token_urlsafe(24)
        self._t[ticket] = (principal, now + self.ttl_s)
        while len(self._t) > self.max_items:
            self._t.popitem(last=False)
        return ticket

    def redeem(self, ticket: str | None, now: float) -> Principal | None:
        """One use only: the ticket is deleted whether or not it is still valid."""
        if not ticket:
            return None
        entry = self._t.pop(ticket, None)
        return entry[0] if entry and entry[1] >= now else None

    def _expire(self, now: float) -> None:
        while self._t and next(iter(self._t.values()))[1] < now:
            self._t.popitem(last=False)
