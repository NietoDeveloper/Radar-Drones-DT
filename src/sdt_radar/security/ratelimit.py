"""Token-bucket rate limiting and brute-force lockout (in-memory, bounded)."""

from __future__ import annotations

from collections import OrderedDict


class RateLimiter:
    """Token bucket per key. ``allow`` returns (allowed, seconds until a token is available)."""

    def __init__(self, rate_per_s: float, burst: float, max_keys: int = 50_000) -> None:
        self.rate, self.burst, self.max_keys = rate_per_s, burst, max_keys
        self._b: OrderedDict[str, tuple[float, float]] = OrderedDict()  # key -> (tokens, last)

    def allow(self, key: str, now: float, cost: float = 1.0) -> tuple[bool, float]:
        tokens, last = self._b.pop(key, (self.burst, now))
        tokens = min(self.burst, tokens + max(now - last, 0.0) * self.rate)
        ok = tokens >= cost
        if ok:
            tokens -= cost
        self._b[key] = (tokens, now)
        while len(self._b) > self.max_keys:  # bounded memory under key-spraying attacks
            self._b.popitem(last=False)
        return ok, 0.0 if ok else (cost - tokens) / self.rate


class AuthLockout:
    """Lock a client (IP) for ``lock_s`` after ``max_failures`` failed authentications in ``window_s``."""

    def __init__(self, max_failures: int = 8, window_s: float = 60.0, lock_s: float = 300.0,
                 max_keys: int = 50_000) -> None:
        self.max_failures, self.window_s, self.lock_s, self.max_keys = max_failures, window_s, lock_s, max_keys
        self._fails: OrderedDict[str, list[float]] = OrderedDict()
        self._locked: dict[str, float] = {}

    def locked(self, client: str, now: float) -> float:
        """Seconds of lock remaining (0 if not locked)."""
        until = self._locked.get(client, 0.0)
        if until <= now:
            self._locked.pop(client, None)
            return 0.0
        return until - now

    def failure(self, client: str, now: float) -> bool:
        """Register a failure; returns True if this one triggered a lock."""
        hits = [t for t in self._fails.pop(client, []) if now - t < self.window_s] + [now]
        self._fails[client] = hits
        while len(self._fails) > self.max_keys:
            self._fails.popitem(last=False)
        if len(hits) >= self.max_failures:
            self._locked[client] = now + self.lock_s
            self._fails.pop(client, None)
            return True
        return False

    def success(self, client: str) -> None:
        self._fails.pop(client, None)
