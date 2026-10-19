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
    version = db.migrate(settings.db_path)  # create/upgrade the schema before taking traffic
    log.info("database ready: %s (schema v%d)", settings.db_path, version)

    repository = EventRepository(settings.db_path)
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

        content_type = request.headers.get("content-type", "")
        try:
            # SQLite calls are blocking, so they run in a worker thread to keep the loop free.
            result = await asyncio.to_thread(service.ingest, carrier, content_type, body)
        except UnknownCarrier:
            raise HTTPException(404, f"unknown carrier '{carrier}'") from None
        except InvalidPayload as exc:
            raise HTTPException(422, str(exc)) from None
        return IngestResponse(
            status=result.outcome, carrier=result.carrier, event_id=result.event_id
        )

    # ---------------------------------------------------------------------- observability
    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        await asyncio.to_thread(repository.ping)  # proves the database is reachable too
        return {"status": "ok"}

    @app.get("/stats", response_model=StatsOut, tags=["ops"])
    async def stats() -> dict[str, Any]:
        return await asyncio.to_thread(repository.stats)

    @app.get("/events", response_model=list[EventOut], tags=["data"])
    async def list_events(
        carrier: str | None = None,
        tracking_number: str | None = None,
        after_id: AfterId = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            lambda: repository.list_events(
                carrier=carrier, tracking_number=tracking_number, after_id=after_id, limit=limit
            )
        )

    # ------------------------------------------------------------------------ extraction
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
