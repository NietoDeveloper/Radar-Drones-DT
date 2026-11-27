-- Reference schema for a PostgreSQL + TimescaleDB deployment of the Store protocol.
-- STATUS: design reference only. The v1 repository ships SQLite and in-memory stores;
-- this schema has NOT been executed or tested against a real server.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE tracks (ENCES tracks(track_id),
  lat          double precision NOT NULL,
  lon          double precision NOT NULL,
  alt_m        real NOT NULL,
  vel_e_mps    real, vel_n_mps real, vel_u_mps real,
  speed_mps    real, heading_deg real,
  position_sigma_m real,
  confidence   real,
  sensors      text[]
);
SELECT create_hypertable('track_points', 't', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON track_points (track_id, t DESC);
ALTER TABLE track_points SET (timescaledb.compress, timescaledb.compress_segmentby = 'track_id');
SELECT add_compression_policy('track_points', INTERVAL '7 days');
SELECT add_retention_policy('track_points', INTERVAL '180 days');

CREATE TABLE alerts (
  alert_id   text PRIMARY KEY,
  state      text NOT NULL,
  updated_at timestamptz NOT NULL,
  payload    jsonb NOT NULL
);
CREATE INDEX ON alerts (updated_at DESC);
CREATE TABLE zones (id text PRIMARY KEY, payload jsonb NOT NULL);
