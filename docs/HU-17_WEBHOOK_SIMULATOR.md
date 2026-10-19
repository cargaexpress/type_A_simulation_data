# HU-17 — Webhook Simulator (Push) — 5 Type A Carriers

**Feature:** F3 — Type A carrier webhooks · **Receiving side:** our own API · **Carriers:** send
events over HTTP `POST` with different formats · **Mode:** continuous · **Carriers:** 5

## User story

> As a data team, I want to build a webhook simulator for 5 Type A carriers to test real event
> ingestion.

## Acceptance criteria

> The simulator sends events with different formats, varied statuses, and duplicate/out-of-order
> events.

| Criterion | How it is met | Verified by |
| --- | --- | --- |
| **Different formats** | 5 carriers, 5 formats: flat JSON, nested JSON, Spanish JSON, XML, form-urlencoded. | `test_formats.py` (golden samples + round trip), `test_runner.py::…decodable_body…` |
| **Varied statuses** | 10–11 custom statuses per carrier (minimum is 6), picked at random along realistic shipment journeys. | `test_catalog.py`, `test_generator.py`, `test_end_to_end.py::…six_statuses…` |
| **Duplicate events** | Byte-identical resend of the same event id, configurable rate and delay. | `test_chaos.py`, `test_runner.py::…duplicates…`, `test_repository.py` (idempotent storage) |
| **Out-of-order events** | An event arrives after a later event of its own shipment, configurable rate. | `test_chaos.py`, `test_end_to_end.py` (receiver independently counts the same disorder) |
| **Real event ingestion** | The receiver API ingests all 5 formats, translates statuses and stores events ACID-safe. | `test_api.py`, `test_end_to_end.py` |

## Sub-tasks

| Ticket | Sub-task | Where |
| --- | --- | --- |
| RIWI-83 | Simulator service that generates random events for each carrier | `domain/generator.py`, `formats/encoders.py`, `simulator/runner.py` |
| RIWI-84 | Catalog of at least 6 custom statuses per carrier | `domain/catalog.py` |
| RIWI-85 | Inject duplicate and out-of-order events in a configurable way | `domain/chaos.py`, `simulator/config.py` |
| RIWI-86 | Dockerize the simulator separately from the backend | `Dockerfile`, `docker-compose.yml` (own image, own lifecycle, no backend needed) |

## Beyond the original scope (v2)

* The **receiver API** (`webhook_simulator/receiver/`) replaces v1's in-memory "sink": it
  decodes the 5 formats, maps statuses and persists to SQLite (ACID, idempotent).
* **Data extraction** for other projects (NDJSON/CSV export, incremental pulls, DB snapshot):
  see [EXTRACTING_DATA.md](EXTRACTING_DATA.md).
* **One command** (`docker compose up --build`) starts the whole thing.
