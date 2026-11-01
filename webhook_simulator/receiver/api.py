"""HTTP layer. Routes only translate HTTP <-> service calls; no business rules in here."""

import asyncio
import csv
import io
import json
import logging
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from webhook_simulator import __version__
from webhook_simulator.receiver import db
from webhook_simulator.receiver.config import ReceiverSettings
from webhook_simulator.receiver.repository import EVENT_COLUMNS, EventRepository
from webhook_simulator.receiver.schemas import EventOut, IngestResponse, StatsOut
from webhook_simulator.receiver.service import IngestService, InvalidPayload, UnknownCarrier

log = logging.getLogger("webhook_simulator.receiver")

AfterId = Annotated[int, Query(ge=0, description="Only rows with id greater than this")]


def _ndjson(rows: Iterable[dict[str, Any]]) -> Iterator[str]:
    for row in rows:
        yield json.dumps(row, ensure_ascii=False) + "\n"


def _csv(rows: Iterable[dict[str, Any]]) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    def flush() -> str:
        chunk = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return chunk

    writer.writerow(EVENT_COLUMNS)
    for row in rows:
        writer.writerow([row[column] for column in EVENT_COLUMNS])
        if buffer.tell() > 64_000:  # stream in chunks instead of building one giant string
            yield flush()
    yield flush()


def create_app(
    settings: ReceiverSettings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or ReceiverSettings()
    target_db = settings.target_database
    version = db.migrate(target_db)  # create/upgrade the schema before taking traffic
    log.info("database ready: %s (schema v%d)", target_db, version)

    repository = EventRepository(target_db, retention_days=settings.retention_days)
    service = IngestService(repository, clock=clock)

    app = FastAPI(
        title="Carrier webhook receiver",
        version=__version__,
        description="Receives push events from the 5 Type A carriers and stores them (ACID).",
    )

    # ------------------------------------------------------------------ webhook ingestion
    @app.post("/webhooks/{carrier}", response_model=IngestResponse, tags=["webhooks"])
    async def receive_webhook(carrier: str, request: Request) -> IngestResponse:
        # Cheap guard first: refuse oversized bodies before reading them.
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_body_bytes:
            raise HTTPException(413, "payload too large")
        body = await request.body()
        if len(body) > settings.max_body_bytes:
            raise HTTPException(413, "payload too large")

        content_type = request.headers.get("content-type", "application/octet-stream")
        try:
            result = await asyncio.to_thread(service.ingest, carrier, content_type, body)
        except UnknownCarrier as exc:
            raise HTTPException(404, str(exc)) from exc
        except InvalidPayload as exc:
            raise HTTPException(422, str(exc)) from exc

        return IngestResponse(
            status=result.outcome,
            carrier=result.carrier,
            event_id=result.event_id,
        )

    # ------------------------------------------------------------------------- maintenance
    @app.post("/maintenance/cleanup", tags=["maintenance"])
    def cleanup_old_events(days: int | None = None) -> dict[str, int]:
        """Delete events older than N days (defaults to retention_days setting)."""
        deleted = repository.cleanup_old_events(days)
        return {"deleted_events": deleted}

    # ---------------------------------------------------------------------- observability
    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        repository.ping()
        return {"status": "ok"}

    @app.get("/stats", response_model=StatsOut, tags=["system"])
    def stats() -> dict[str, Any]:
        return repository.stats()

    # --------------------------------------------------------------------- data inspection
    @app.get("/events", response_model=list[EventOut], tags=["events"])
    def list_events(
        carrier: str | None = None,
        tracking_number: str | None = None,
        after_id: AfterId = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> list[dict[str, Any]]:
        return repository.list_events(
            carrier=carrier,
            tracking_number=tracking_number,
            after_id=after_id,
            limit=limit,
        )

    # ----------------------------------------------------------------------------- exports
    @app.get("/exports/events.ndjson", tags=["export"])
    def export_ndjson(after_id: AfterId = 0, carrier: str | None = None) -> StreamingResponse:
        """Every event, one JSON object per line. Use `after_id` for incremental pulls."""
        rows = repository.iter_events(after_id=after_id, carrier=carrier)
        return StreamingResponse(_ndjson(rows), media_type="application/x-ndjson")

    @app.get("/exports/events.csv", tags=["export"])
    def export_csv(after_id: AfterId = 0, carrier: str | None = None) -> StreamingResponse:
        """Same data as the NDJSON export, as CSV."""
        rows = repository.iter_events(after_id=after_id, carrier=carrier)
        return StreamingResponse(
            _csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="events.csv"'},
        )

    return app
