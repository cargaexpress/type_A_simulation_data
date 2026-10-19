# Getting the generated data into another project

Everything the carriers "sent" ends up in the receiver's database. There are **four ways** to use
it from another project. Pick the one that matches what you are doing.

| I want to… | Use |
| --- | --- |
| Load the events into a notebook / script / database | [1. HTTP export](#1-http-export-the-easy-one) |
| Hand over the whole database as a file | [2. SQLite snapshot](#2-sqlite-snapshot-the-whole-database-as-one-file) |
| Let my other docker project call the receiver | [3. Shared docker network](#3-shared-docker-network) |
| Test **my backend's** ingestion with these carriers | [4. Push straight into your backend](#4-push-straight-into-your-backend-no-receiver-needed) |

Plus [5. reuse the code](#5-reuse-the-code-itself) and [6. replay a run](#6-replay-the-exact-same-run).

---

## 1. HTTP export (the easy one)

The stack must be running (`docker compose up`). Nothing to install on the other side.

```bash
# Everything, one JSON object per line
curl -o events.ndjson localhost:9000/exports/events.ndjson

# Same thing as CSV
curl -o events.csv localhost:9000/exports/events.csv

# Only one carrier
curl -o delta.ndjson 'localhost:9000/exports/events.ndjson?carrier=delta'
```

### Incremental pulls (only what's new)

Every row has an `id` that grows with arrival order. Remember the biggest one you've seen and
ask only for rows after it:

```bash
curl 'localhost:9000/exports/events.ndjson?after_id=1500'
```

### From Python

```python
import httpx, json

BASE = "http://localhost:9000"

def pull_new_events(last_id: int = 0):
    """Yield every event with id > last_id (streams, so it's fine for big exports)."""
    with httpx.stream("GET", f"{BASE}/exports/events.ndjson", params={"after_id": last_id}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                yield json.loads(line)

rows = list(pull_new_events())
last_id = rows[-1]["id"] if rows else 0     # save this for next time
```

With pandas it's one line:

```python
import pandas as pd
df = pd.read_json("http://localhost:9000/exports/events.ndjson", lines=True)
# or: pd.read_csv("http://localhost:9000/exports/events.csv")
```

> The exports read in short batches and never hold a long lock, so downloading a big file
> won't slow down incoming webhooks.

---

## 2. SQLite snapshot (the whole database as one file)

The data lives in a Docker volume (`receiver-data`) at `/data/events.db`. Don't copy that file
while the receiver is running: SQLite keeps recent writes in a side file (`-wal`), so a plain
copy can miss them. Take a **consistent snapshot** with SQLite's own backup API instead; it is
safe while events keep arriving:

```bash
# 1) snapshot inside the container
docker compose exec receiver python -c \
  "import sqlite3; s=sqlite3.connect('/data/events.db'); d=sqlite3.connect('/data/snapshot.db'); s.backup(d); d.close()"

# 2) copy it out to your machine
docker compose cp receiver:/data/snapshot.db ./events.db

# 3) use it from anywhere
sqlite3 events.db "SELECT carrier, canonical_status, COUNT(*) FROM events GROUP BY 1, 2;"
```

```python
import sqlite3, pandas as pd
df = pd.read_sql("SELECT * FROM events", sqlite3.connect("events.db"))
```

The file is self-describing: tables `events` and `rejected_events`; the column dictionary is in
[ARCHITECTURE.md](ARCHITECTURE.md#data-model). Handy queries:

```sql
-- how many repeats did each carrier send?
SELECT carrier, SUM(delivery_count - 1) AS duplicates FROM events GROUP BY carrier;

-- one shipment's history in the order it HAPPENED vs the order it ARRIVED
SELECT id AS arrival, occurred_at, raw_status, canonical_status
FROM events WHERE tracking_number = 'ALP1234567890' ORDER BY occurred_at;

-- everything we could not understand
SELECT carrier, reason, raw_body FROM rejected_events;
```

Want to start from scratch? `docker compose down -v` deletes the volume (and all events).

---

## 3. Shared docker network

If your other project also runs on Docker, join this stack's network and call the receiver by
name. In the **other** project's `docker-compose.yml`:

```yaml
services:
  my-app:
    # ...
    networks: [default, webhook-simulator]

networks:
  webhook-simulator:
    name: webhook-simulator_default   # "<project name>_default" of this stack
    external: true
```

Now `my-app` can call `http://receiver:9000/exports/events.ndjson` (or `/events`, `/stats`…).
Start this stack first so the network exists.

---

## 4. Push straight into your backend (no receiver needed)

The simulator doesn't care who is listening. Aim it at any URL that has `{carrier}` in it:

```bash
# Backend running on your machine (port 8000). Starts ONLY the simulator:
docker compose run --rm --no-deps \
  -e SIM_TARGET_URL_TEMPLATE='http://host.docker.internal:8000/webhooks/{carrier}' \
  simulator

# Or put it in .env so `docker compose up simulator` uses it
#   SIM_TARGET_URL_TEMPLATE=http://host.docker.internal:8000/webhooks/{carrier}
```

Without Docker: `uv run python -m webhook_simulator --target-url-template 'http://localhost:8000/webhooks/{carrier}'`.

Your backend must accept `POST /webhooks/alpha|beta|gamma|delta|epsilon` and understand each
carrier's format (see the table in the [README](../README.md#the-5-carriers); the decoders in
`webhook_simulator/formats/decoders.py` are a working reference implementation).

---

## 5. Reuse the code itself

`webhook_simulator/domain/` and `webhook_simulator/formats/` are plain Python with no web or
database code. Copy those two folders into another project and you get:

```python
import random
from webhook_simulator.domain.catalog import CARRIERS_BY_SLUG
from webhook_simulator.domain.generator import EventGenerator
from webhook_simulator.formats import encode, decode

gen = EventGenerator([CARRIERS_BY_SLUG["delta"]], random.Random(1))
event = gen.new_shipment()[0]                          # a realistic event
request = encode(CARRIERS_BY_SLUG["delta"].payload_format, event)
print(request.content_type, request.body)              # exactly what Delta would POST
print(decode(CARRIERS_BY_SLUG["delta"].payload_format, request.body))   # and parsed back
```

The only third-party dependency of those two folders is `defusedxml` (used by the XML decoder).

---

## 6. Replay the exact same run

Fix a seed and you get the same events, ids, duplicates and ordering every time:

```bash
SIM_SEED=42 SIM_MAX_EVENTS=1000 docker compose up --build
```

Great for reproducing a bug: share the seed and the settings, and a colleague gets the same
stream of events.
