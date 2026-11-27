# Security

This document states what the backend protects, how, and — equally important — what it does **not**.
Nothing here has been penetration-tested or independently audited; treat it as defence in depth that
reduces risk, not a certification.

## 1. Threat model

| Asset | Threat | Mitigation in v2 |
|---|---|---|
| Track picture / alerts (integrity) | Forged or replayed detections injected by a network attacker | Per-sensor **HMAC-SHA256 signatures**, ±30 s clock-skew window, replay cache, fail-closed secrets |
| Track picture (availability) | Flooding ingest or the API | Per-sensor and per-IP **token buckets**, bounded reorder buffer, bounded WebSocket queues, body-size limit |
| API data (confidentiality) | Anonymous or low-privilege access | **Hashed API keys with roles** (viewer < operator < admin), constant-time verification |
| API keys | Brute force / credential stuffing | **Lockout** after repeated failures (per IP), rate limiting, audited failures |
| API keys | Leakage in URLs and logs (browser WebSockets) | **Single-use WebSocket tickets**; `?api_key=` refused by default |
| Configuration / zones / sensors | Unauthorised change, repudiation | Role checks + **tamper-evident audit log** (hash chain) |
| Browser clients | XSS-style content sniffing, clickjacking, caching | Hardening headers, strict CSP on API paths, CORS allow-list, Host allow-list |
| Secrets | Exposure in config, API output or logs | Secrets only from environment/files, never serialised to API responses, only hashes stored for keys |
| Alert consumers | Spoofed or replayed webhook calls | **Signed webhooks** (`X-SDT-Signature` over timestamp + body) |
| Edge → hub link | Tampering / eavesdropping | HTTPS to the hub (TLS), operator key, optional per-sensor signatures end-to-end |

## 2. Authentication and authorisation

### API keys

`sdt-radar keygen --role operator --id edge-7` prints a token **once** and the config record to store:

```toml
[[api.keys]]
id = "edge-7"
role = "operator"
sha256 = "9f2c…"        # SHA-256 of the secret part only
```

* Token format `sdtr_<id>_<secret>`; the secret is 256 bits from `secrets.token_urlsafe`. The server keeps
  only the SHA-256 digest (a high-entropy random secret needs no slow KDF) and compares in constant time;
  an unknown key id costs the same work as a wrong secret (no id oracle).
* `SDT_RADAR_API_KEY` (legacy single key) maps to an **admin** principal. Prefer `[[api.keys]]`.
* With no keys configured the API is **open** — acceptable only on loopback. `sdt-radar serve` refuses to
  bind another address without at least one key.
* **Rotation / revocation:** create the new key, deploy it to clients, delete the old record from the
  config and restart. There is no hot reload in v2.

### Roles

| Capability | viewer | operator | admin |
|---|:--:|:--:|:--:|
| Read tracks, history, archive, alerts, zones, sensors, metrics, `/metrics`, WebSocket | ✔ | ✔ | ✔ |
| Obtain a WebSocket ticket, `whoami` | ✔ | ✔ | ✔ |
| HTTP detection ingest; create / delete zones | | ✔ | ✔ |
| Register sensors; read the audit log and its head hash | | | ✔ |

### Brute force and abuse

* Per-IP **token bucket** (`api.rate_limit_per_s`, `rate_limit_burst`) → HTTP 429 + `Retry-After`.
* **Lockout:** `lockout_failures` failed authentications within `lockout_window_s` lock that IP for
  `lockout_s`, even for valid keys (so the attacker cannot confirm a guess).
* Behind a reverse proxy set `api.trust_proxy_headers = true` so limits apply to the real client IP;
  **never** enable it when the service is directly reachable (the header would be attacker-controlled).

### WebSocket authentication

Browsers cannot send headers on a WebSocket handshake, and a key in the URL ends up in proxy and access
logs. Flow: `POST /api/v1/auth/ws-ticket` (key in a header) → one-time ticket valid
`ws_ticket_ttl_s` (30 s) → `wss://…/ws/v1/stream?ticket=…`. Non-browser clients may use the
`X-API-Key` header. `?api_key=` works only with `api.allow_query_api_key = true`.

## 3. Ingest security

| Path | Authentication |
|---|---|
| `POST /api/v1/ingest/detections` | Operator API key (header) |
| UDP 9100 / TCP 9101 | **None by default** — unsigned plots are accepted from anyone who can reach the port. Restrict at the network layer **and/or** require signatures |

### Signed detections (recommended whenever UDP/TCP are reachable beyond a trusted segment)

Per sensor, set a secret **from the environment or a file** (never in the config text):

```toml
[[sensors]]
id = "fmcw-1"
kind = "radar_fmcw"
hmac_secret_env = "SDT_FMCW1_SECRET"     # or hmac_secret_file = "/run/secrets/fmcw1"
```

The sender adds `"sig"` = hex HMAC-SHA256(secret, canonical JSON of the detection without `sig`),
where canonical JSON means sorted keys, no whitespace, `None` fields omitted, numbers as Python's `json`
module writes them (shortest round-trip repr). Reference implementation: `sdt_radar.security.sign`.

Server-side order of checks (cheapest first): parse → per-sensor rate limit → signature → timestamp within
`ingest.max_clock_skew_s` → replay cache (a signature is accepted once) → schema validation.

* A sensor **with** a secret must always sign (unsigned or wrongly signed data is rejected and audited).
* `ingest.require_signatures = true` makes signatures mandatory for every sensor.
* If a declared secret cannot be loaded, startup fails (**fail closed**) — a sensor never silently falls
  back to unsigned.
* Signatures give *authenticity and integrity*, not confidentiality (use TLS/VPN for that).
* In-process callers (`Pipeline.ingest`, simulator, replay) are trusted and unsigned by design.

### Rate limits

`ingest.default_rate_limit_per_s` (5 000/s) and per-sensor `rate_limit_per_s` bound each sensor's accepted
detections on the network path; excess is counted as `rejected_rate`.

## 4. Transport and HTTP hardening

* **TLS:** `sdt-radar serve --tls-cert cert.pem --tls-key key.pem` (HTTPS/WSS, HSTS emitted), or
  terminate TLS in a reverse proxy. Binding a public address without TLS prints a warning.
* Headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy: same-origin`; on API paths additionally
  `Cache-Control: no-store` and `Content-Security-Policy: default-src 'none'`. The `Server` header is stripped.
* `api.max_body_bytes` (5 MB) rejects oversized bodies (declared or streamed) with 413.
* `api.allowed_hosts` enables a Host-header allow-list; `api.cors_origins` is an explicit allow-list
  (methods GET/POST/DELETE, headers `x-api-key`, `content-type`, `x-request-id`).
* Every request carries an `X-Request-ID` (accepted if well-formed, otherwise generated) that appears in
  JSON logs for correlation.

## 5. Audit log

`[audit] path = "data/audit.jsonl"` (enabled by default). One JSON line per security-relevant event:
`auth_failure`, `forbidden`, `zone_create`, `zone_delete`, `sensor_register`, `ingest_rejected`
(bad/missing signature, replay), `retention_prune`.

* Each record contains `prev` (hash of the previous record) and `hash = SHA-256(prev ‖ canonical(record))`.
  Editing, deleting or re-ordering any line breaks the chain; `sdt-radar audit-verify data/audit.jsonl`
  exits non-zero and names the first bad line. The server refuses to append to a log that fails verification.
* **Limit:** truncating the *tail* leaves a valid chain. Periodically store `GET /api/v1/audit/head`
  (`seq` + `hash`) somewhere an attacker with host access cannot edit (another host, WORM storage, a ticket).
* A per-action flood cap (`audit.max_per_min`) stops an attacker from filling the disk with audit
  records; suppressed events are counted (`sdt_audit_suppressed_total`).

## 6. Outbound webhooks

`[[notify.webhooks]]` deliver alerts with headers `X-SDT-Timestamp` and
`X-SDT-Signature: sha256=HMAC(secret, timestamp + "." + body)`. Receivers should verify the signature in
constant time and reject timestamps older than a few minutes. Delivery is asynchronous, bounded (queue of
1 000, drops counted), retried with back-off, and can never block tracking. URLs are operator-configured
(not user input), so there is no SSRF surface through the API.

## 7. Hardening checklist

1. Bind to loopback or a private interface; publish through a reverse proxy with TLS.
2. Create one key per client with the lowest role it needs; keep the tokens in a secret manager.
3. Sign every sensor that sends over UDP/TCP; give each its own secret; set `require_signatures = true`.
4. Firewall 9100/udp and 9101/tcp to sensor hosts only; run NTP/PTP everywhere (the skew window depends on it).
5. Keep `data/` readable only by the service user; back up and rotate `audit.jsonl`; anchor its head hash.
6. Turn on JSON logging and scrape `/metrics`; alert on `rejected_bad_signature`, `rejected_replay`,
   `auth_failure` audit events and 429s.
7. Run as a non-root user (the Dockerfile does) with a read-only root filesystem where possible.
8. Patch dependencies regularly (`pip install -U`), and re-run the test suite.

## 8. What v2 does not do

* **No TLS client-certificate (mTLS) authentication, no OIDC/SSO, no user accounts or per-user quotas.**
* **No hot reload of keys**; revocation needs a restart.
* **No encryption at rest** for the SQLite file, recordings or the audit log (use disk encryption).
* **Unsigned UDP/TCP ingest is trivially spoofable** — this is why signatures exist; they are opt-in.
* **No protection against network-layer floods** (SYN/UDP volumetric attacks): use the network.
* Rate limiting and lockout state are **in memory** and per process (reset on restart; not shared across replicas).
* Remote ID and RF data are untrusted by nature (spoofable); fusion improves a track, it does not authenticate it.
* The audit chain cannot detect tail truncation by itself (see §5).
* Signature canonicalisation assumes Python-style number formatting; non-Python senders must match it exactly.
* No third-party penetration test or code audit has been performed.
