"""API keys with roles. Only SHA-256 hashes are stored; verification is constant-time.

Token format: ``sdtr_<key_id>_<secret>``. ``key_id`` is public (appears in audit logs); the 256-bit
``secret`` never leaves the operator. A high-entropy random secret needs no slow KDF: a plain SHA-256
digest is the right tool (the secret cannot be brute-forced or looked up in a rainbow table).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import IntEnum

PREFIX = "sdtr"


class Role(IntEnum):
    """Hierarchical roles: each role can do everything the lower ones can."""

    viewer = 1  # read tracks, history, alerts, zones, sensors, metrics; WebSocket
    operator = 2  # + HTTP detection ingest, create/delete zones
    admin = 3  # + register sensors, read the audit log

    @classmethod
    def parse(cls, name: str) -> Role:
        try:
            return cls[name]
        except KeyError as exc:
            raise ValueError(f"unknown role '{name}' (use viewer, operator or admin)") from exc


@dataclass(frozen=True)
class Principal:
    key_id: str
    role: Role

    def allows(self, needed: Role) -> bool:
        return self.role >= needed


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_key(role: Role, key_id: str | None = None) -> tuple[str, dict[str, str]]:
    """Return (token to hand to the client, config record to store). The token is shown exactly once."""
    kid = key_id or secrets.token_hex(4)
    if "_" in kid:
        raise ValueError("key_id must not contain '_'")
    secret = secrets.token_urlsafe(32)
    return f"{PREFIX}_{kid}_{secret}", {"id": kid, "role": role.name, "sha256": _digest(secret)}


class ApiKeyStore:
    def __init__(self, records: list[tuple[str, Role, str]], legacy_admin_key: str | None = None) -> None:
        self._by_id = {kid: (role, h.lower()) for kid, role, h in records}
        self._legacy = _digest(legacy_admin_key) if legacy_admin_key else None
        self._dummy = _digest("dummy-secret-for-constant-time")

    @property
    def enabled(self) -> bool:
        return bool(self._by_id) or self._legacy is not None

    def verify(self, token: str | None) -> Principal | None:
        if not token:
            return None
        parts = token.split("_", 2)
        if len(parts) == 3 and parts[0] == PREFIX:
            role_hash = self._by_id.get(parts[1])
            stored = role_hash[1] if role_hash else self._dummy  # same work whether or not the id exists
            ok = hmac.compare_digest(_digest(parts[2]), stored)
            return Principal(parts[1], role_hash[0]) if (ok and role_hash) else None
        if self._legacy is not None and hmac.compare_digest(_digest(token), self._legacy):
            return Principal("env", Role.admin)  # single shared key from SDT_RADAR_API_KEY
        return None
