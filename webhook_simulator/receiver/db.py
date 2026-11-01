"""Database plumbing: connections, transactions and schema migrations.

Supports both local SQLite and PostgreSQL / Supabase cloud databases.
"""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None


def is_postgres(target: str | Path) -> bool:
    """Check if the connection target is a PostgreSQL URL."""
    s = str(target).strip().lower()
    return s.startswith("postgres://") or s.startswith("postgresql://")


# SQLite schema migrations
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """
        CREATE TABLE events (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier           TEXT    NOT NULL,
            event_id          TEXT    NOT NULL,
            tracking_number   TEXT    NOT NULL,
            raw_status        TEXT    NOT NULL,
            canonical_status  TEXT,
            occurred_at       TEXT    NOT NULL,
            location          TEXT    NOT NULL,
            content_type      TEXT    NOT NULL,
            raw_body          TEXT    NOT NULL,
            delivery_count    INTEGER NOT NULL DEFAULT 1 CHECK (delivery_count >= 1),
            first_received_at TEXT    NOT NULL,
            last_received_at  TEXT    NOT NULL,
            UNIQUE (carrier, event_id)
        ) STRICT
        """,
        "CREATE INDEX idx_events_shipment ON events (carrier, tracking_number, occurred_at)",
        """
        CREATE TABLE rejected_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier      TEXT NOT NULL,
            content_type TEXT NOT NULL,
            raw_body     TEXT NOT NULL,
            reason       TEXT NOT NULL,
            received_at  TEXT NOT NULL
        ) STRICT
        """,
    ),
)

# PostgreSQL / Supabase schema definitions
PG_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS events (
        id                BIGSERIAL PRIMARY KEY,
        carrier           TEXT NOT NULL,
        event_id          TEXT NOT NULL,
        tracking_number   TEXT NOT NULL,
        raw_status        TEXT NOT NULL,
        canonical_status  TEXT,
        occurred_at       TEXT NOT NULL,
        location          TEXT NOT NULL,
        content_type      TEXT NOT NULL,
        raw_body          TEXT NOT NULL,
        delivery_count    INTEGER NOT NULL DEFAULT 1 CHECK (delivery_count >= 1),
        first_received_at TEXT NOT NULL,
        last_received_at  TEXT NOT NULL,
        UNIQUE (carrier, event_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_shipment ON events (carrier, tracking_number, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_events_received ON events (first_received_at)",
    """
    CREATE TABLE IF NOT EXISTS rejected_events (
        id           BIGSERIAL PRIMARY KEY,
        carrier      TEXT NOT NULL,
        content_type TEXT NOT NULL,
        raw_body     TEXT NOT NULL,
        reason       TEXT NOT NULL,
        received_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rejected_received ON rejected_events (received_at)",
)


def connect_sqlite(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and strict pragmas."""
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def connect_postgres(url: str):
    """Open a PostgreSQL connection using psycopg with dict_row."""
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Please install psycopg[binary].")
    cleaned_url = str(url).replace("postgres://", "postgresql://", 1)
    return psycopg.connect(cleaned_url, row_factory=dict_row)


def connect(target: str | Path):
    """Open a database connection depending on the target string."""
    if is_postgres(target):
        return connect_postgres(str(target))
    return connect_sqlite(target)


@contextmanager
def transaction(conn: Any) -> Iterator[Any]:
    """All-or-nothing transaction block for both SQLite and PostgreSQL."""
    if hasattr(conn, "transaction"):
        with conn.transaction():
            yield conn
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def migrate(target: str | Path) -> int:
    """Initialize or upgrade schema on the target database."""
    if is_postgres(target):
        with closing(connect_postgres(str(target))) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    for stmt in PG_SCHEMA:
                        cur.execute(stmt)
        return 1

    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_sqlite(target)) as conn:
        with transaction(conn):
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            for version, statements in enumerate(MIGRATIONS, start=1):
                if version <= current:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version}")
        return conn.execute("PRAGMA user_version").fetchone()[0]
