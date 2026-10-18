# Webhook Simulator — 5 Type-A Carriers (Push)

**Backend-independent** service that sends HTTP tracking events just like 5 real carriers would (each with its own format and custom states), including configurable **duplicate** and **out-of-order** events. Designed for testing event ingestion.

| Carrier | Message Format | Content-Type | Example Custom States |
|---|---|---|---|
| `alpha`   | Flat JSON (snake_case, UTC ISO time)             | `application/json` | `IN_TRANSIT`, `HELD_AT_CUSTOMS`, `RETURNED_TO_SENDER` |
| `beta`    | Nested JSON (camelCase, numeric code, ms time)  | `application/json` | `100`, `300`, `600`, `999` |
| `gamma`   | Spanish JSON (local time -05:00)                | `application/json; charset=utf-8` | `En reparto`, `Intento fallido`, `Novedad` |
| `delta`   | XML (short codes, compact time)                 | `application/xml` | `PCK`, `HUB`, `NDL`, `RTS` |
| `epsilon` | Form (`x-www-form-urlencoded`, seconds time)    | `application/x-www-form-urlencoded` | `Collected from sender`, `Held - address verification` |

Each carrier has **10 or 11 states** (minimum required: 6). Alpha, Beta, and Gamma use exact states already existing in the backend mapping; Delta and Epsilon are new (see `HU-17_SIMULADOR_WEBHOOKS.md`).

## Run with Docker (Recommended)

```bash
cd simulator
docker compose up --build          # simulator + test sink receiver on :9000
curl localhost:9000/stats              # view how many messages arrived, and how many identical repeats
curl 'localhost:9000/received?carrier=delta&limit=3'
docker compose run --rm tests          # automated tests ("test" profile)
docker compose down
```

Variables like `SIM_DUPLICATE_RATE=0.5 docker compose up` (or a `.env` file next to compose) alter the behavior.
To send to a backend running on your machine: `SIM_TARGET_URL_TEMPLATE=http://host.docker.internal:8000/webhooks/{carrier}`.

## Run without Docker

```bash
cd simulator
uv sync --python 3.12
uv run python -m webhook_simulator.sink --port 9000 &            # test receiver
uv run python -m webhook_simulator --max-events 200 --seed 1     # simulator
uv run python -m webhook_simulator --dry-run --max-events 10     # preview only, does not send
uv run pytest -q
```

## Configuration (Environment Variable / Command-Line Option)

| Variable | Option | Default | Description |
|---|---|---|---|
| `SIM_TARGET_URL_TEMPLATE` | `--target-url-template` | `http://localhost:9000/webhooks/{carrier}` | Destination; `{carrier}` is replaced by the slug |
| `SIM_CARRIERS` | `--carriers` | all 5 | Carriers to simulate |
| `SIM_RATE` | `--rate` | `5` | Messages per second (0 = no pause) |
| `SIM_SHIPMENTS_PER_BATCH` | `--shipments-per-batch` | `20` | Shipments mixed together in each batch |
| `SIM_MAX_EVENTS` | `--max-events` | `0` | Stop after N messages (0 = indefinite) |
| `SIM_DUPLICATE_RATE` | `--duplicate-rate` | `0.10` | Probability of resending an identical event |
| `SIM_OUT_OF_ORDER_RATE` | `--out-of-order-rate` | `0.10` | Probability of an event arriving after a subsequent event in its shipment |
| `SIM_DUPLICATE_MAX_DELAY` | `--duplicate-max-delay` | `5` | A duplicate arrives at most N messages later |
| `SIM_SEED` | `--seed` | random | Repeats the exact same simulation |
| `SIM_DRY_RUN` | `--dry-run` / `--no-dry-run` | `false` | Prints messages (JSON per line) without sending them |
| `SIM_REQUEST_TIMEOUT` | `--timeout` | `5` | Maximum seconds per dispatch |

Command-line options take precedence over environment variables. Upon completion (or via Ctrl+C / `docker stop`), it prints a summary: sent, delivered (2xx), failed, unique, duplicates, out-of-order. With `--max-events` and zero successful deliveries, it exits with code 1.

## How Events Are Generated

1. Each shipment goes through a lifecycle (normal, with exception, return, loss, or cancellation), and at each step, one of the carrier's custom states is chosen at random. Timestamps for a single shipment are always chronological.
2. Shipments within a batch are shuffled together.
3. **Out-of-order:** with probability `out_of_order_rate`, an event is swapped with a subsequent event from the same shipment (e.g., "Delivered" arrives before "Out for delivery").
4. **Duplicates:** with probability `duplicate_rate`, the exact same byte-for-byte message (same id) is resent between 0 and `duplicate_max_delay` messages later.

## Test Receiver (`webhook_simulator.sink`)

Standard library only. In-memory storage of incoming requests without interpretation: `POST /webhooks/<carrier>`, `GET /stats`, `GET /received?carrier=&limit=`, `GET /health`. Does not replace backend ingestion.

## Structure

```
webhook_simulator/  catalog.py (states) · generator.py (events) · formats.py (5 formats)
                    chaos.py (duplicates/disorder) · runner.py (delivery) · config.py · sink.py · __main__.py
tests/              automated tests · Dockerfile · docker-compose.yml · pyproject.toml / uv.lock
```