# Architecture

## 1. Goals and non-goals

**Goals:** ingest detections from heterogeneous sensors; keep one coherent picture of every airborne
target (tracks); tell drones from birds; alert on protected zones; record everything; serve a real-time
UI with < 500 ms display latency; scale

## 2. Data flow
   alerts ◄── AlertEngine ◄── tracks ◄── MultiTargetTracker ◄──────────────────────────────┘sotropic). Geodetic: 

  (p50 237 ms, p99 249 ms), + ≤ 200 ms until the next WebSocket snapshot ≈ 450 ms worst case.
  Lowering `fusion.reorder_window_s` trades latency for ordering robustness.

## 5. Concurrency model

| Context | Does | Shares with others |
|---|---|---|
| asyncio event loop (main) | UDP/TCP servers, 50 ms pipeline tick, WebSocket hub, REST handlers | `Pipeline` guarded by an `RLock` |
| SQLite writer thread | Batches queue → `executemany` → commit every 200 ms | `SimpleQueue` only |
| Reader connection | REST history/archive queries (`asyncio.to_thread`) | WAL permits concurrent read |

