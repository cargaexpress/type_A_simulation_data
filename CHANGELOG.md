# Changelog

## 2.0.0

A cleanup-and-upgrade release on top of v1 (same 5 carriers, same formats, same statuses).

### Added
- **Receiver API** (FastAPI) that ingests all 5 formats and stores events in SQLite with ACID
  guarantees: atomic transactions, constraints, WAL, `synchronous=FULL`, idempotent upsert.
- Unreadable payloads are parked in `rejected_events` (answered `422`) instead of being lost.
- Data extraction: `/events`, `/stats`, `/exports/events.ndjson`, `/exports/events.csv`
  (incremental with `after_id`), plus a documented SQLite snapshot recipe.
- `docs/` with architecture, data-extraction guide and HU-17 traceability.
- Ruff linting (also runs in `docker compose run --rm tests`), `.env.example`, `.dockerignore`.
- Many more tests (146): ACID behaviour, concurrency, all formats, end to end.

### Changed
- Code reorganised in layers: `domain/` → `formats/` → `simulator/` and `receiver/`.
- Everything (code, comments, docs, tests, logs, CLI help) is now in English.
- `docker compose up --build` starts the receiver **and** the simulator; the simulator waits for
  the receiver to be healthy and runs continuously. Events persist in the `receiver-data` volume.
- Configuration moved to `pydantic-settings` (same `SIM_*` variables, CLI flags still win).
- The sender is a small interface (`HttpSender` / `DryRunSender`), so the runner has no HTTP code.
- Sending rate now follows a fixed schedule, so the real rate matches `SIM_RATE`; a stop request
  interrupts the pause immediately instead of waiting for it to finish.
- XML is parsed with `defusedxml`.
- Dataclasses use `slots`, statuses are `StrEnum`s, timestamps use `datetime.UTC`.

### Removed / breaking
- `webhook_simulator/sink.py` and the `sink` compose service → replaced by the receiver
  (`python -m webhook_simulator.receiver`, service `receiver`, same port 9000).
- The `--timeout` flag is now `--request-timeout` (matches `SIM_REQUEST_TIMEOUT`).
- `tests/helpers.py` (its decoders are now the real ones in `formats/decoders.py`).
- README commands no longer start with `cd simulator`: the project lives at the repo root.

### Unchanged on purpose
- `python -m webhook_simulator ...` still starts the simulator.
- Carrier statuses, formats, `{carrier}` URL template and the `SIM_*` variable names.
