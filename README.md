# Webhook Simulator + Receiver API — 5 Type A Carriers (Push)

Two small services that work as a pair, so you can test **real event ingestion** without
depending on any real carrier or on the backend:

| Service | What it does |
| --- | --- |
| **simulator** | Plays the role of 5 carriers. Pushes tracking events over HTTP `POST`, each carrier with **its own format and its own statuses**, including configurable **duplicate** and **out-of-order** events. Runs continuously. |
| **receiver** | Our own API. Receives those webhooks, understands all 5 formats, translates statuses to ours and stores everything in an **ACID** database, ready to be extracted into another project. |

> Context: this is the **F3 — Type A carrier webhooks** feature (user story **HU-17**).
> See [`docs/HU-17_WEBHOOK_SIMULATOR.md`](docs/HU-17_WEBHOOK_SIMULATOR.md) for how every
> acceptance criterion is covered.

## Quick start (Docker)

```bash
docker compose up --build          # receiver + simulator, running continuously
```

That's it. Docker builds the image, starts the receiver, waits until it's healthy, then starts
the simulator. In another terminal:

```bash
curl localhost:9000/stats                                # what has arrived so far
curl 'localhost:9000/events?carrier=delta&limit=3'       # peek at some stored events
docker compose logs -f simulator                         # what is being sent
open http://localhost:9000/docs                          # interactive API docs (Swagger UI)
```

Other handy commands:

```bash
docker compose run --rm tests      # lint (ruff) + the whole test suite
docker compose down                # stop; events are kept in the "receiver-data" volume
docker compose down -v             # stop AND wipe every stored event
```

Want to tweak the simulation? Either put variables in a `.env` file (start from
[`.env.example`](.env.example)) or pass them inline:

```bash
SIM_RATE=20 SIM_DUPLICATE_RATE=0.5 SIM_SEED=7 docker compose up --build
```

**Taking the data to another project?** → [`docs/EXTRACTING_DATA.md`](docs/EXTRACTING_DATA.md)

## The 5 carriers

| Carrier | Message format | Content-Type | Example custom statuses |
| --- | --- | --- | --- |
| `alpha` | Flat JSON (snake_case, UTC ISO time) | `application/json` | `IN_TRANSIT`, `HELD_AT_CUSTOMS`, `RETURNED_TO_SENDER` |
| `beta` | Nested JSON (camelCase, numeric code, epoch milliseconds) | `application/json` | `100`, `300`, `600`, `999` |
| `gamma` | Spanish JSON (local time `-05:00`) | `application/json; charset=utf-8` | `En reparto`, `Intento fallido`, `Novedad` |
| `delta` | XML (short codes, compact time) | `application/xml` | `PCK`, `HUB`, `NDL`, `RTS` |
| `epsilon` | Form (`x-www-form-urlencoded`, epoch seconds) | `application/x-www-form-urlencoded` | `Collected from sender`, `Held - address verification` |

Every carrier has **10 or 11 statuses** (the minimum required is 6). Alpha, Beta and Gamma use
exactly the statuses already present in the backend's `state_mapping`; Delta and Epsilon are new.
(Gamma's statuses stay in Spanish on purpose: that's what the carrier really sends.)

## Receiver API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/webhooks/{carrier}` | Ingest one event. `200` stored or duplicate · `404` unknown carrier · `413` too big · `422` unreadable payload (parked, not lost) |
| `GET` | `/health` | Liveness + database check |
| `GET` | `/stats` | Totals, duplicates, out-of-order, rejected, per-carrier counts |
| `GET` | `/events` | Browse stored events (`carrier`, `tracking_number`, `after_id`, `limit`) |
| `GET` | `/exports/events.ndjson` | Full export, one JSON object per line (`after_id`, `carrier`) |
| `GET` | `/exports/events.csv` | Same data as CSV |

Duplicates answer **200 on purpose**: a real carrier keeps retrying on errors, so the receiver
acknowledges a repeat and just counts it (`delivery_count`).

## Simulator configuration

Every option is a `SIM_*` environment variable **and** a command-line flag
(flags win). `--help` lists them all.

| Variable | Flag | Default | Description |
| --- | --- | --- | --- |
| `SIM_TARGET_URL_TEMPLATE` | `--target-url-template` | `http://localhost:9000/webhooks/{carrier}` (`http://receiver:9000/...` in Docker) | Destination; `{carrier}` becomes the carrier slug |
| `SIM_CARRIERS` | `--carriers` | all 5 | Comma-separated carriers to simulate |
| `SIM_RATE` | `--rate` | `5` | Messages per second (`0` = no pauses) |
| `SIM_SHIPMENTS_PER_BATCH` | `--shipments-per-batch` | `20` | Shipments mixed together in each batch |
| `SIM_MAX_EVENTS` | `--max-events` | `0` | Stop after N messages (`0` = run forever) |
| `SIM_DUPLICATE_RATE` | `--duplicate-rate` | `0.10` | Probability of re-sending an identical event |
| `SIM_OUT_OF_ORDER_RATE` | `--out-of-order-rate` | `0.10` | Probability of an event arriving after a later event of its shipment |
| `SIM_DUPLICATE_MAX_DELAY` | `--duplicate-max-delay` | `5` | A duplicate arrives at most N messages later |
| `SIM_SEED` | `--seed` | random | Replays the exact same simulation |
| `SIM_DRY_RUN` | `--dry-run` / `--no-dry-run` | `false` | Print messages (one JSON per line) without sending |
| `SIM_REQUEST_TIMEOUT` | `--request-timeout` | `5` | Max seconds per request |

On exit (or Ctrl+C / `docker stop`) the simulator logs a summary: sent, delivered (2xx), failed,
unique, duplicates, out-of-order. With `--max-events` and **zero** successful deliveries it
exits with code `1`.

## Receiver configuration

| Variable | Default | Description |
| --- | --- | --- |
| `RECEIVER_HOST` | `0.0.0.0` | Interface to listen on |
| `RECEIVER_PORT` | `9000` | Port to listen on |
| `RECEIVER_DB_PATH` | `data/events.db` (`/data/events.db` in Docker) | SQLite file |
| `RECEIVER_MAX_BODY_BYTES` | `1000000` | Bodies above this get a `413` |
| `RECEIVER_ACCESS_LOG` | `false` | One log line per request (noisy at 5 msg/s) |

## How events are generated

1. Each shipment follows a life cycle (normal, with exception, return, loss or cancellation).
   At every step one of the carrier's **own** statuses is picked at random. Timestamps inside a
   shipment are always chronological.
2. Shipments of a batch are shuffled together.
3. **Out of order:** with probability `out_of_order_rate`, an event swaps places with a later
   event of the same shipment (e.g. "Delivered" arrives before "Out for delivery").
4. **Duplicates:** with probability `duplicate_rate`, the exact same message (same id, same
   bytes) is re-sent between 0 and `duplicate_max_delay` messages later.

## Run without Docker

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync
uv run python -m webhook_simulator.receiver &                      # API on :9000
uv run python -m webhook_simulator --max-events 200 --seed 1       # simulator
uv run python -m webhook_simulator --dry-run --max-events 10       # preview only, sends nothing
uv run ruff check . && uv run pytest -q                            # lint + tests
```

## Project structure

```
webhook_simulator/
├── domain/       catalog.py (carriers + statuses) · models.py · generator.py · chaos.py
│                 -> pure logic, no I/O. Safe to copy into another project.
├── formats/      encoders.py (what carriers send) · decoders.py (what the receiver reads)
├── simulator/    config.py · sender.py (HTTP / dry-run) · runner.py · stats.py · cli.py
└── receiver/     config.py · api.py · service.py · repository.py · db.py · schemas.py
tests/            one test file per module + test_end_to_end.py (simulator -> receiver)
docs/             ARCHITECTURE.md · EXTRACTING_DATA.md · HU-17_WEBHOOK_SIMULATOR.md
Dockerfile · docker-compose.yml · pyproject.toml · uv.lock · .env.example · CHANGELOG.md
```

Design notes, the layering rules and how each ACID property is covered live in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
