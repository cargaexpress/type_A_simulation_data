"""Repository: the ONLY place that knows SQL. Everything else works with plain Python values."""

from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from webhook_simulator.receiver.db import connect, is_postgres, transaction

EVENT_COLUMNS: tuple[str, ...] = (
    "id", "carrier", "event_id", "tracking_number", "raw_status", "canonical_status",
    "occurred_at", "location", "content_type", "raw_body", "delivery_count",
    "first_received_at", "last_received_at",
)  # fmt: skip

_SELECT_EVENTS = f"SELECT {', '.join(EVENT_COLUMNS)} FROM events"


class EventRepository:
    def __init__(self, target: str | Path, retention_days: int = 3) -> None:
        self._target = target
        self._is_pg = is_postgres(target)
        self._retention_days = retention_days

    def _param_char(self) -> str:
        return "%s" if self._is_pg else "?"

    def cleanup_old_events(self, days: int | None = None) -> int:
        """Delete events older than N days to prevent storage exhaustion.
        
        Returns count of deleted events.
        """
        days = self._retention_days if days is None else days
        if days <= 0:
            return 0
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        param = self._param_char()
        deleted = 0
        with closing(connect(self._target)) as conn, transaction(conn):
            if self._is_pg:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM events WHERE first_received_at < {param}", (cutoff,))
                    deleted = cur.rowcount
                    cur.execute(f"DELETE FROM rejected_events WHERE received_at < {param}", (cutoff,))
            else:
                cur = conn.execute(f"DELETE FROM events WHERE first_received_at < {param}", (cutoff,))
                deleted = cur.rowcount
                conn.execute(f"DELETE FROM rejected_events WHERE received_at < {param}", (cutoff,))
        return deleted

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
        param = self._param_char()
        sql = f"""
        INSERT INTO events (
            carrier, event_id, tracking_number, raw_status, canonical_status,
            occurred_at, location, content_type, raw_body,
            first_received_at, last_received_at
        ) VALUES ({', '.join([param] * 11)})
        ON CONFLICT (carrier, event_id) DO UPDATE SET
            delivery_count   = events.delivery_count + 1,
            last_received_at = EXCLUDED.last_received_at
        RETURNING delivery_count
        """
        params = (
            carrier, event_id, tracking_number, raw_status, canonical_status,
            occurred_at, location, content_type, raw_body, received_at, received_at,
        )

        with closing(connect(self._target)) as conn, transaction(conn):
            if self._is_pg:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
            else:
                row = conn.execute(sql, params).fetchone()

        return row["delivery_count"] == 1

    def save_rejected(
        self, *, carrier: str, content_type: str, raw_body: str, reason: str, received_at: str
    ) -> None:
        """Park a payload we couldn't understand, so nothing the carriers send is ever lost."""
        param = self._param_char()
        sql = (
            f"INSERT INTO rejected_events (carrier, content_type, raw_body, reason, received_at)"
            f" VALUES ({param}, {param}, {param}, {param}, {param})"
        )
        params = (carrier, content_type, raw_body, reason, received_at)

        with closing(connect(self._target)) as conn, transaction(conn):
            if self._is_pg:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
            else:
                conn.execute(sql, params)

    # ------------------------------------------------------------------------------- reads
    def ping(self) -> None:
        with closing(connect(self._target)) as conn:
            if self._is_pg:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            else:
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
        param = self._param_char()
        clauses, params = [f"id > {param}"], [after_id]
        if carrier:
            clauses.append(f"carrier = {param}")
            params.append(carrier)
        if tracking_number:
            clauses.append(f"tracking_number = {param}")
            params.append(tracking_number)

        sql = f"{_SELECT_EVENTS} WHERE {' AND '.join(clauses)} ORDER BY id LIMIT {param}"
        full_params = (*params, limit)

        with closing(connect(self._target)) as conn:
            if self._is_pg:
                with conn.cursor() as cur:
                    cur.execute(sql, full_params)
                    return list(cur.fetchall())
            return [dict(row) for row in conn.execute(sql, full_params)]

    def iter_events(
        self, *, after_id: int = 0, carrier: str | None = None, batch_size: int = 1000
    ) -> Iterator[dict[str, Any]]:
        """Walk ALL events in arrival order, one short query per batch."""
        cursor = after_id
        while True:
            batch = self.list_events(carrier=carrier, after_id=cursor, limit=batch_size)
            yield from batch
            if len(batch) < batch_size:
                return
            cursor = batch[-1]["id"]

    def stats(self) -> dict[str, Any]:
        with closing(connect(self._target)) as conn:
            if self._is_pg:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) AS unique_events, COALESCE(SUM(delivery_count), 0) AS deliveries FROM events"
                    )
                    totals = cur.fetchone()
                    cur.execute(
                        "SELECT carrier, COUNT(*) AS unique_events, "
                        "COALESCE(SUM(delivery_count), 0) AS deliveries, "
                        "COUNT(DISTINCT raw_status) AS distinct_statuses "
                        "FROM events GROUP BY carrier ORDER BY carrier"
                    )
                    per_carrier = cur.fetchall()
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM events e WHERE EXISTS (
                            SELECT 1 FROM events earlier
                            WHERE earlier.carrier = e.carrier
                              AND earlier.tracking_number = e.tracking_number
                              AND earlier.id < e.id
                              AND earlier.occurred_at > e.occurred_at
                        )
                        """
                    )
                    row_ooo = cur.fetchone()
                    out_of_order = row_ooo["count"] if isinstance(row_ooo, dict) else row_ooo[0]
                    cur.execute("SELECT COUNT(*) FROM rejected_events")
                    row_rej = cur.fetchone()
                    rejected = row_rej["count"] if isinstance(row_rej, dict) else row_rej[0]
            else:
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

        total_deliv = int(totals["deliveries"])
        unique_ev = int(totals["unique_events"])
        return {
            "total_deliveries": total_deliv,
            "unique_events": unique_ev,
            "duplicates": total_deliv - unique_ev,
            "out_of_order": int(out_of_order),
            "rejected": int(rejected),
            "per_carrier": {
                row["carrier"]: {
                    "unique_events": int(row["unique_events"]),
                    "deliveries": int(row["deliveries"]),
                    "distinct_statuses": int(row["distinct_statuses"]),
                }
                for row in per_carrier
            },
        }
