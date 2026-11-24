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
