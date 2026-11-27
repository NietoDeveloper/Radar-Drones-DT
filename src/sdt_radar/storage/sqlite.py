"""SQLite store (WAL) with a dedicated writer thread.

* Relational metadata (tracks, alerts, zones) and time-series points live in one file.
* Writes ar