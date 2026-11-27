"""Per-sensor HMAC-SHA256 signing of detections, with replay protection.

Signature = HMAC-SHA256(secret, canonical JSON of the detection without ``sig``), hex encoded.
Canonical JSON: keys sorted, no whitespace, ``None`` fields omitted, numbers as Python's ``json`` writes
them (shortest round-trip repr). Senders in other languages must produce the same text.
Replay protection: signed detections must carry a timestamp within the allowed clock skew and a
signature that has not been seen inside that window.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


def canonical(obj: dict[str, Any]) -> bytes:
    body = {k: v for k, v in obj.items() if k != "sig" and v is not None}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sign(secret: bytes, obj: dict[str, Any]) -> str:
    return hmac.new(secret, canonical(obj), hashlib.sha256).hexdigest()


def verify(secret: bytes, obj: dict[str, Any]) -> bool:
    sig = obj.get("sig")
    if not isinstance(sig, str):
        return False
    try:
        return hmac.compare_digest(sign(secret, obj), sig)
    except (TypeError, ValueError):  # non-serialisable / NaN content
        return False


def load_secret(env: str | None, file: str | None) -> bytes | None:
    """Resolve a sensor secret from an environment variable or a file (never from the config text)."""
    import os

    if env and os.environ.get(env):
        return os.environ[env].strip().encode()
    if file:
        data = Path(file).read_text(encoding="utf-8").strip()
        return data.encode() if data else None
    return None


class ReplayCache:
    """Remember signatures for ``ttl_s``; ``seen`` returns True if already used (a replay)."""

    def __init__(self, ttl_s: float, max_items: int = 500_000) -> None:
        self.ttl_s, self.max_items = ttl_s, max_items
        self._s: OrderedDict[str, float] = OrderedDict()

    def seen(self, sig: str, now: float) -> bool:
        while self._s and (next(iter(self._s.values())) < now - self.ttl_s or len(self._s) > self.max_items):
            self._s.popitem(last=False)
        if sig in self._s:
            return True
        self._s[sig] = now
        return False
