"""Database behaviour: idempotency, ACID guarantees, pagination and stats."""

import sqlite3
import threading
from contextlib import closing

import pytest

from webhook_simulator.receiver import db
from webhook_simulator.receiver.repository import EVENT_COLUMNS, EventRepository


def _event(n=1, *, carrier="alpha", tracking="ALP1", occurred="2026-10-13T12:00:00.000Z", **extra):
    base = {
        "carrier": carrier, "event_id": f"evt-{n}", "tracking_number": tracking,
        "raw_status": "IN_TRANSIT", "canonical_status": "IN_TRANSIT",
        "occurred_at": occurred, "location": "Cali", "content_type": "application/json",
        "raw_body": "{}", "received_at": "2026-10-13T12:00:01.000Z",
    }  # fmt: skip
    return base | extra


# ------------------------------------------------------------------------- idempotency
def test_a_repeated_event_is_not_stored_twice_and_bumps_the_counter(repository):
    assert repository.save_event(**_event(1)) is True
    assert repository.save_event(**_event(1, received_at="2026-10-13T12:05:00.000Z")) is False
    assert repository.save_event(**_event(1)) is False

    [row] = repository.list_events()
    assert row["delivery_count"] == 3
    assert row["first_received_at"] == "2026-10-13T12:00:01.000Z"


def test_same_event_id_from_two_different_carriers_is_not_a_duplicate(repository):
    assert repository.save_event(**_event(1, carrier="alpha")) is True
    assert repository.save_event(**_event(1, carrier="beta")) is True


def test_concurrent_identical_requests_still_create_one_row(repository):
    results, errors = [], []

    def worker():
        try:
            results.append(repository.save_event(**_event(1)))
        except Exception as exc:  # pragma: no cover - would be a real failure
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert results.count(True) == 1 and results.count(False) == 11
    assert repository.list_events()[0]["delivery_count"] == 12


# ----------------------------------------------------------------------------- ACID
def test_atomicity_a_failure_inside_a_transaction_rolls_everything_back(db_path, repository):
    with pytest.raises(RuntimeError), closing(db.connect(db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO rejected_events (carrier, content_type, raw_body, reason, received_at)"
            " VALUES ('a', 'b', 'c', 'd', 'e')"
        )
        raise RuntimeError("something broke halfway")
    assert repository.stats()["rejected"] == 0


def test_consistency_the_database_itself_refuses_bad_rows(db_path, repository):
    with closing(db.connect(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):  # NOT NULL
            conn.execute("INSERT INTO events (carrier) VALUES ('alpha')")
        repository.save_event(**_event(1))
        with pytest.raises(sqlite3.IntegrityError):  # CHECK delivery_count >= 1
            conn.execute("UPDATE events SET delivery_count = 0")
        with pytest.raises(sqlite3.IntegrityError):  # STRICT: text into an integer column
            conn.execute("UPDATE events SET delivery_count = 'many'")


def test_isolation_readers_are_not_blocked_by_an_open_write_transaction(db_path, repository):
    repository.save_event(**_event(1))
    with closing(db.connect(db_path)) as writer, db.transaction(writer):
        writer.execute("UPDATE events SET location = 'uncommitted'")
        # WAL mode: a reader sees the last COMMITTED state, and doesn't wait.
        assert repository.list_events()[0]["location"] == "Cali"
    assert repository.list_events()[0]["location"] == "uncommitted"


def test_durability_data_is_there_after_reopening_the_file(db_path, repository):
    repository.save_event(**_event(1))
    assert EventRepository(db_path).list_events()[0]["event_id"] == "evt-1"


def test_connections_use_wal_and_full_sync(db_path, repository):
    with closing(db.connect(db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL


# -------------------------------------------------------------------------- migrations
def test_migrate_is_idempotent_and_records_the_version(db_path):
    assert db.migrate(db_path) == len(db.MIGRATIONS)
    EventRepository(db_path).save_event(**_event(1))
    assert db.migrate(db_path) == len(db.MIGRATIONS)  # second run changes nothing
    assert len(EventRepository(db_path).list_events()) == 1  # ...and loses nothing


def test_migrate_creates_missing_parent_folders(tmp_path):
    nested = tmp_path / "a" / "b" / "events.db"
    db.migrate(nested)
    assert nested.exists()


# -------------------------------------------------------------------------- reads
def test_list_events_filters_and_paginates_by_cursor(repository):
    for n in range(1, 8):
        repository.save_event(
            **_event(n, carrier="alpha" if n % 2 else "beta", tracking=f"T{n % 3}")
        )

    first = repository.list_events(limit=3)
    assert [r["id"] for r in first] == [1, 2, 3]
    second = repository.list_events(after_id=first[-1]["id"], limit=3)
    assert [r["id"] for r in second] == [4, 5, 6]

    assert {r["carrier"] for r in repository.list_events(carrier="beta")} == {"beta"}
    assert {r["tracking_number"] for r in repository.list_events(tracking_number="T1")} == {"T1"}


def test_iter_events_walks_everything_in_arrival_order_across_batches(repository):
    for n in range(1, 26):
        repository.save_event(**_event(n))
    ids = [row["id"] for row in repository.iter_events(batch_size=10)]
    assert ids == list(range(1, 26))
    assert [r["id"] for r in repository.iter_events(after_id=20, batch_size=10)] == [
        21,
        22,
        23,
        24,
        25,
    ]


def test_rows_expose_exactly_the_documented_columns(repository):
    repository.save_event(**_event(1))
    assert tuple(repository.list_events()[0]) == EVENT_COLUMNS


# -------------------------------------------------------------------------- stats
def test_stats_count_duplicates_disorder_and_rejections(repository):
    repository.save_event(**_event(1, occurred="2026-10-13T12:00:00.000Z"))
    repository.save_event(**_event(2, occurred="2026-10-13T14:00:00.000Z"))
    repository.save_event(**_event(3, occurred="2026-10-13T13:00:00.000Z"))  # late arrival
    repository.save_event(**_event(2))  # duplicate
    repository.save_event(**_event(4, tracking="OTHER", occurred="2026-10-13T01:00:00.000Z"))
    repository.save_rejected(
        carrier="alpha", content_type="x", raw_body="junk", reason="bad", received_at="now"
    )

    stats = repository.stats()
    assert stats["unique_events"] == 4
    assert stats["total_deliveries"] == 5
    assert stats["duplicates"] == 1
    assert stats["out_of_order"] == 1  # event 3 arrived after event 2, which happened later
    assert stats["rejected"] == 1
    assert stats["per_carrier"]["alpha"] == {
        "unique_events": 4, "deliveries": 5, "distinct_statuses": 1,
    }  # fmt: skip


def test_stats_on_an_empty_database(repository):
    stats = repository.stats()
    assert stats["unique_events"] == stats["total_deliveries"] == stats["duplicates"] == 0
    assert stats["per_carrier"] == {}
