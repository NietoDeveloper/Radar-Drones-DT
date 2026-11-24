-- Reference schema for a PostgreSQL + TimescaleDB deployment of the Store protocol.
-- STATUS: design reference only. The v1 repository ships SQLite and in-memory stores;
-- this schema has NOT been executed or tested against a real server.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE tracks (
  track_id         text PRIMARY KEY,
  seq              integer NOT NULL,
  status           text NOT NULL,
  target_class     text NOT NULL,
  class_confidence real,
  confidence       real,
  first_seen       timestamptz NOT NULL,
  last_seen        timestamptz NOT NULL,
  sensors          text[] NOT NULL DEFAULT '{}',
  rcs_dbsm         real,
  payload          jsonb NOT NULL
);
CREATE INDEX ON tracks (last_seen DESC);
CREATE INDEX ON tracks (target

CREATE TABLE track_points (
  t            timestamptz NOT NULL,
  track_id     text NOT NULL REFERENCES tracks(track_id),
  lat          double precision NOT NULL,
  lon          double precision NOT NULL,
  alt_m        real NOT NULL,
  vel_e_mps    real, vel_n_mps real, vel_u_mps real,
  speed_mps    real, heading_deg real,
  position_sigma_m real,
  confidence   real,
