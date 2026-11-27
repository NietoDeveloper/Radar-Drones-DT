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
  