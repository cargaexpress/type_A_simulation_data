"""Repository: the ONLY place that knows SQL. Everything else works with plain Python values."""

from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

from webhook_simulator.receiver.db import connect, transaction

# Column order used by the exports (kept here so API and tests agree on it).
EVENT_COLUMNS: tuple[str, ...] = (
    "id", "carrier", "event_id", "tracking_number", "raw_status", "canonical_status",
    "occurred_at", "location", "content_type", "raw_body", "delivery_count",
    "first_received_at", "last_received_at",
)  # fmt: skip

_SELECT_EVENTS = f"SELECT {', '.join(EVENT_COLUMNS)} FROM events"


class EventRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------------------ writes
    def save_event(
        self,
        *,
        carrier: str,
        event_id: str,
        tracking_number: str,
        raw_status: str,
        canonical_status: str | None,
        occurred_at: str,
        location: str,
        content_type: str,
        raw_body: str,
        received_at: str,
    ) -> bool:
        """Store an event. Returns True if it's new, False if it was a repeat of a known one.

        A repeat (same carrier + event_id) just bumps `delivery_count`: no second row, no
        error, so carrier retries are harmless. Insert-or-bump is ONE atomic statement,
        so two identical requests racing each other can never create two rows.
        """
        with closing(connect(self._db_path)) as conn, transaction(conn):
            row = conn.execute(
                """
                INSERT INTO events (
                    carrier, event_id, tracking_number, raw_status, canonical_status,
                    occurred_at, location, content_type, raw_body,
                    first_received_at, last_received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (carrier, event_id) DO UPDATE SET
                    delivery_count   = delivery_count + 1,
                    last_received_at = excluded.last_received_at
                RETURNING delivery_count
                """,
                (carrier, event_id, tracking_number, raw_status, canonical_status,
                 occurred_at, location, content_type, raw_body, received_at, received_at),
            ).fetchone()  # fmt: skip
        return row["delivery_count"] == 1

    def save_rejected(
        self, *, carrier: str, content_type: str, raw_body: str, reason: str, received_at: str
    ) -> None:
        """Park a payload we couldn't understand, so nothing the carriers send is ever lost."""
        with closing(connect(self._db_path)) as conn, transaction(conn):
            conn.execute(
                "INSERT INTO rejected_events (carrier, content_type, raw_body, reason, received_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (carrier, content_type, raw_body, reason, received_at),
            )

    # ------------------------------------------------------------------------------- reads
    def ping(self) -> None:
        with closing(connect(self._db_path)) as conn:
            conn.execute("SELECT 1").fetchone()

    def list_events(
        self,
        *,
        carrier: str | None = None,
        tracking_number: str | None = None,
        after_id: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """One page of events in arrival order. Pass the last `id` you saw as `after_id`."""
        clauses, params = ["id > ?"], [after_id]
        if carrier:
            clauses.append("carrier = ?")
            params.append(carrier)
        if tracking_number:
            clauses.append("tracking_number = ?")
            params.append(tracking_number)
        sql = f"{_SELECT_EVENTS} WHERE {' AND '.join(clauses)} ORDER BY id LIMIT ?"
        with closing(connect(self._db_path)) as conn:
            return [dict(row) for row in conn.execute(sql, (*params, limit))]

    def iter_events(
        self, *, after_id: int = 0, carrier: str | None = None, batch_size: int = 1000
    ) -> Iterator[dict[str, Any]]:
        """Walk ALL events in arrival order, one short query per batch.

        No long-lived connection or read lock is held while the client downloads, so a slow
        export never blocks incoming webhooks.
        """
        cursor = after_id
        while True:
            batch = self.list_events(carrier=carrier, after_id=cursor, limit=batch_size)
            yield from batch
            if len(batch) < batch_size:
                return
            cursor = batch[-1]["id"]

    def stats(self) -> dict[str, Any]:
        with closing(connect(self._db_path)) as conn:
            totals = conn.execute(
                "SELECT COUNT(*) AS unique_events, COALESCE(SUM(delivery_count), 0) AS deliveries"
                " FROM events"
            ).fetchone()
            per_carrier = conn.execute(
                "SELECT carrier, COUNT(*) AS unique_events,"
                " SUM(delivery_count) AS deliveries,"
                " COUNT(DISTINCT raw_status) AS distinct_statuses"
                " FROM events GROUP BY carrier ORDER BY carrier"
            ).fetchall()
            # An event is "out of order" if something LATER in its shipment arrived before it.
            out_of_order = conn.execute(
                """
                SELECT COUNT(*) FROM events e WHERE EXISTS (
                    SELECT 1 FROM events earlier
                    WHERE earlier.carrier = e.carrier
                      AND earlier.tracking_number = e.tracking_number
                      AND earlier.id < e.id
                      AND earlier.occurred_at > e.occurred_at
                )
                """
            ).fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM rejected_events").fetchone()[0]
        return {
            "total_deliveries": totals["deliveries"],  # every accepted POST, repeats included
            "unique_events": totals["unique_events"],
            "duplicates": totals["deliveries"] - totals["unique_events"],
            "out_of_order": out_of_order,
            "rejected": rejected,
            "per_carrier": {
                row["carrier"]: {
                    "unique_events": row["unique_events"],
                    "deliveries": row["deliveries"],
                    "distinct_statuses": row["distinct_statuses"],
                }
                for row in per_carrier
            },
        }
