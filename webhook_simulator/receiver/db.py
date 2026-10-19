"""Database plumbing: connections, transactions and schema migrations.

Why SQLite? It's fully ACID, needs no extra container, and the whole database is ONE file
that another project can copy and open directly (see docs/EXTRACTING_DATA.md).
All the SQL stays behind `repository.py`, so moving to PostgreSQL later only touches
the infrastructure layer.

How each ACID letter is covered here:
    Atomicity    every write runs inside one explicit transaction (all or nothing)
    Consistency  STRICT tables + NOT NULL + CHECK + UNIQUE constraints reject bad data
    Isolation    WAL mode (readers never block the writer) + BEGIN IMMEDIATE (writers queue up)
    Durability   synchronous=FULL, so a committed event survives a crash or power cut
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

# One entry per schema version. To change the schema, APPEND a new tuple of statements;
# never edit an old one. `PRAGMA user_version` remembers how far this file has gotten.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        # v1: events (one row per distinct event) + a parking lot for payloads we can't parse
        """
        CREATE TABLE events (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,  -- also the ARRIVAL order
            carrier           TEXT    NOT NULL,
            event_id          TEXT    NOT NULL,
            tracking_number   TEXT    NOT NULL,
            raw_status        TEXT    NOT NULL,   -- exactly what the carrier sent
            canonical_status  TEXT,               -- our translation (NULL = unmapped status)
            occurred_at       TEXT    NOT NULL,   -- ISO-8601 UTC, sorts correctly as text
            location          TEXT    NOT NULL,
            content_type      TEXT    NOT NULL,
            raw_body          TEXT    NOT NULL,   -- original payload, untouched
            delivery_count    INTEGER NOT NULL DEFAULT 1 CHECK (delivery_count >= 1),
            first_received_at TEXT    NOT NULL,
            last_received_at  TEXT    NOT NULL,
            UNIQUE (carrier, event_id)            -- this is what makes retries idempotent
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


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with the pragmas we always want."""
    # isolation_level=None -> we manage transactions ourselves (see `transaction`).
    # check_same_thread=False -> FastAPI hops between worker threads; each connection is
    # only ever used by one caller at a time, so that's safe.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")  # wait up to 10 s for a lock instead of failing
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """All-or-nothing block. Commits on success, rolls back on ANY exception."""
    conn.execute("BEGIN IMMEDIATE")  # take the write lock now, not halfway through
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def migrate(path: str | Path) -> int:
    """Bring the database file up to the latest schema. Safe to run on every startup."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as conn:
        # Whole migration in one transaction: either the schema is fully upgraded or untouched.
        with transaction(conn):
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            for version, statements in enumerate(MIGRATIONS, start=1):
                if version <= current:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version}")  # PRAGMAs can't take ? params
        return conn.execute("PRAGMA user_version").fetchone()[0]
