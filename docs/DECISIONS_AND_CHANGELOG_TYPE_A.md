# Architectural Decisions & Technical Changelog — Type A Simulator

This document compiles all architectural decisions, cloud infrastructure changes, optimizations, and implementations performed for the **Type A Webhook Simulator and Receiver Service** (`type_A_simulation_data`).

---

## 1. Summary of Changes & Git Log

| Commit | Type | Summary | Key Files Affected |
| :--- | :--- | :--- | :--- |
| **`fb80c3a`** | `refactor` | Container footprint optimization using Alpine Linux multi-stage build | `Dockerfile`, `README.md` |
| **`1a81a58`** | `feat` | Dual-database support: SQLite fallback + PostgreSQL / Supabase with auto-retention | `pyproject.toml`, `uv.lock`, `db.py`, `repository.py`, `api.py`, `config.py`, `docker-compose.yml`, `.env.example` |
| **`c64db6f`** | `ci` | GitHub Actions workflow for automated AWS ECR & ECS Fargate deployment | `.github/workflows/deploy.yml`, `task-definition.json`, `Dockerfile`, `docker-compose.yml` |
| **`4333197`** | `fix` | AWS Fargate ECR execution role resolution (`executionRoleArn`) | `.github/workflows/deploy.yml` |
| **`e461753`** | `feat` | Render deployment blueprint configuration & dynamic port binding (`PORT`) | `render.yaml`, `config.py` |
| **`e955ff0`** | `feat` | Continuous automated background simulation engine with control endpoints | `api.py`, `config.py`, `render.yaml`, `task-definition.json` |

---

## 2. Architectural Decisions & Rationale (ADR)

### ADR-01: Container Footprint Optimization (Alpine Linux Multi-Stage)
* **Context**: The baseline Debian `python:3.12-slim` image was 205 MB uncompressed and 49.5 MB compressed, carrying extraneous Debian operating system libraries.
* **Decision**: Refactor the multi-stage build (`builder`, `test`, `runtime`) to use `python:3.12-alpine` with `uv` bytecode ahead-of-time compilation (`UV_COMPILE_BYTECODE=1`) and non-root execution (`app` user with UID 10001).
* **Impact**:
  * Uncompressed disk image reduced from **205 MB to 104 MB (-49.3%)**.
  * Transfer / download footprint reduced from **49.5 MB to 24.6 MB (-50.3%)**.
  * All 146 unit and end-to-end tests passed with 100% compliance.

### ADR-02: Cloud Database Integration (Supabase / PostgreSQL) & Ephemeral Storage
* **Context**: Storing events exclusively in local SQLite docker volumes required persistent storage (EBS / EFS) in AWS, which incurs monthly infrastructure costs and complicates horizontal scaling.
* **Decision**: Add native PostgreSQL support using `psycopg[binary]`.
  * If `DATABASE_URL` (or `RECEIVER_DATABASE_URL`) starts with `postgresql://` or `postgres://`, the receiver uses PostgreSQL / Supabase Session Pooler.
  * If unset, it falls back seamlessly to local SQLite for local testing without breaking any existing workflow.
* **Impact**: Containers become 100% **stateless**. The application can scale, restart, or run across multiple clouds without losing state or needing persistent disk volumes.

### ADR-03: Storage Quota Management & Automated Event Retention
* **Context**: Supabase Free Tier has a 500 MB database quota. Continuous event generation (simulating 5 carriers) risks exhausting storage over time.
* **Decision**: Implement a multi-layered retention strategy:
  1. Built-in application retention: `cleanup_old_events(days)` purges records where `first_received_at < NOW() - INTERVAL '3 days'`.
  2. Scheduled database cleanup: Database extension `pg_cron` can execute daily deletions directly in Postgres.
  3. API Maintenance endpoint: `POST /maintenance/cleanup` exposed for on-demand or external cron maintenance.
* **Impact**: Database size stabilizes permanently between 50 MB and 100 MB, well under the 500 MB threshold.

### ADR-04: Automated Cloud Deployment Architecture (Dual-Target: AWS ECS & Render)
* **Context**: Needed reproducible deployment to both AWS (for formal enterprise infrastructure evaluation) and Render (for permanent, zero-cost public HTTPS URL testing).
* **Decisions**:
  1. **AWS Infrastructure**:
     * Dedicated VPC (`cargaexpress-simuladores-vpc`) with 2 public subnets and **0 NAT Gateways** to ensure $0 networking costs.
     * Shared Security Group (`simuladores-cargaexpress-sg`) opening port 9000 for Type A, 8001–8004 for Type B, and 2222 for Type C.
     * Automated GitHub Actions pipeline building the Alpine Docker image, pushing to private AWS ECR, and deploying to ECS Fargate.
     * Automated resolution of `executionRoleArn` for Fargate to pull private ECR images.
  2. **Render Cloud Infrastructure**:
     * Render Blueprint (`render.yaml`) declaring the container service, health checks at `/health`, and dynamic binding to `PORT` / `RECEIVER_PORT`.
     * Live permanent endpoint: `https://cargaexpress-simulator-a.onrender.com` with managed TLS certificates.

### ADR-05: Continuous In-Process Simulation Engine
* **Context**: Running the simulator as a separate client process required manual terminal execution on developer workstations. The system needed autonomous event generation in the cloud.
* **Decision**: Introduce `DirectIngestSender` and tie the simulation runner to FastAPI's async lifespan:
  * When `AUTO_SIMULATE=true` (configured with `SIM_RATE=0.5`), the receiver starts a background task that generates realistic multi-carrier events directly into `IngestService`.
  * Preserves identical carrier payload formats (JSON flat, JSON nested, Spanish JSON, XML, Form) and chaos patterns (duplicates, out-of-order).
  * Exposes interactive simulation controls in Swagger UI:
    * `GET /simulation/status`
    * `POST /simulation/start?rate=...`
    * `POST /simulation/stop`
  * Root route `GET /` now returns online system health, simulation status, and direct documentation links.

---

## 3. Production Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | System overview, simulation state, and quick navigation links |
| `GET` | `/health` | Liveness probe and database connectivity ping |
| `GET` | `/docs` | Interactive Swagger UI documentation |
| `GET` | `/stats` | Real-time totals, deliveries, duplicates, out-of-order, and per-carrier stats |
| `GET` | `/events` | Paginated event browser (`carrier`, `tracking_number`, `after_id`, `limit`) |
| `GET` | `/exports/events.ndjson` | Streaming NDJSON export for external backend ingestion |
| `GET` | `/exports/events.csv` | CSV export for analytical consumption |
| `POST` | `/webhooks/{carrier}` | Ingestion webhook for alpha, beta, gamma, delta, epsilon |
| `GET` | `/simulation/status` | Current background simulation status and rate |
| `POST` | `/simulation/start` | Start or resume background simulation |
| `POST` | `/simulation/stop` | Pause background simulation |
| `POST` | `/maintenance/cleanup` | Execute manual retention purge for events older than N days |

---

## 4. Cross-Project Integration Contract (For Type B and Backend)

External consumers (Type B, Type C, or the main CargaExpress backend) connect via:

1. **Environment Configuration**:
   ```env
   TYPE_A_SIMULATOR_URL=https://cargaexpress-simulator-a.onrender.com
   ```
2. **Incremental Pull Pattern**:
   * Poll `GET https://cargaexpress-simulator-a.onrender.com/exports/events.ndjson?after_id={last_seen_id}`
   * Parse each newline-delimited JSON payload and update the local database cursor.
