"""The receiver HTTP API, exercised in-process through httpx's ASGI transport."""

import csv
import io
import json

import httpx
import pytest

from webhook_simulator.domain.catalog import CARRIERS, CARRIERS_BY_SLUG
from webhook_simulator.formats import encode
from webhook_simulator.receiver.api import create_app
from webhook_simulator.receiver.config import ReceiverSettings
from webhook_simulator.receiver.repository import EVENT_COLUMNS


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://receiver"
    ) as c:
        yield c


async def _post(client, carrier, event):
    request = encode(CARRIERS_BY_SLUG[carrier.slug].payload_format, event)
    return await client.post(
        f"/webhooks/{carrier.slug}",
        content=request.body,
        headers={"content-type": request.content_type},
    )


async def _events(client, **params):
    return (await client.get("/events", params={"limit": 1000} | params)).json()


async def _fill(client, make_generator, shipments=5):
    count = 0
    for shipment in make_generator().new_batch(shipments):
        for event in shipment:
            await _post(client, CARRIERS_BY_SLUG[event.carrier], event)
            count += 1
    return count


def _lines(response):
    return [json.loads(line) for line in response.text.splitlines()]


# ------------------------------------------------------------------------------ ingestion
@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
async def test_every_carrier_format_is_accepted_and_stored(client, carrier, make_generator):
    event = make_generator().new_shipment(carrier)[0]
    response = await _post(client, carrier, event)
    assert response.status_code == 200
    assert response.json() == {
        "status": "stored", "carrier": carrier.slug, "event_id": event.event_id,
    }  # fmt: skip

    [row] = await _events(client)
    assert row["event_id"] == event.event_id
    assert row["tracking_number"] == event.tracking_number
    assert row["raw_status"] == event.status.raw
    assert row["canonical_status"] == event.status.canonical.value  # translated to OUR status
    assert row["occurred_at"] == event.occurred_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert row["raw_body"]  # the original payload is kept too


async def test_resending_an_event_is_answered_ok_but_flagged_as_duplicate(client, make_generator):
    carrier = CARRIERS[0]
    event = make_generator().new_shipment(carrier)[0]
    assert (await _post(client, carrier, event)).json()["status"] == "stored"
    again = await _post(client, carrier, event)
    assert again.status_code == 200  # 2xx on purpose: the carrier must NOT keep retrying
    assert again.json()["status"] == "duplicate"
    [row] = await _events(client)
    assert row["delivery_count"] == 2


async def test_unknown_carrier_gets_404_and_nothing_is_stored(client):
    assert (await client.post("/webhooks/zeta", content=b"{}")).status_code == 404
    assert await _events(client) == []


async def test_unparseable_payload_gets_422_and_is_parked_not_lost(client):
    response = await client.post("/webhooks/alpha", content=b"definitely not json")
    assert response.status_code == 422
    assert "malformed" in response.json()["detail"]
    stats = (await client.get("/stats")).json()
    assert stats["rejected"] == 1 and stats["unique_events"] == 0


async def test_a_payload_in_the_wrong_carriers_format_is_rejected(client, make_generator):
    delta = CARRIERS_BY_SLUG["delta"]
    xml_event = make_generator().new_shipment(delta)[0]
    body = encode(delta.payload_format, xml_event).body
    assert (await client.post("/webhooks/alpha", content=body)).status_code == 422


async def test_unmapped_status_is_still_stored_with_null_canonical(client):
    body = (
        b'{"event_id":"x1","tracking_number":"ALP9","status":"TELEPORTED",'
        b'"occurred_at":"2026-10-13T12:00:00Z","location":"Cali"}'
    )
    assert (await client.post("/webhooks/alpha", content=body)).status_code == 200
    [row] = await _events(client)
    assert row["raw_status"] == "TELEPORTED" and row["canonical_status"] is None


async def test_oversized_bodies_get_413(db_path):
    app = create_app(ReceiverSettings(db_path=str(db_path), max_body_bytes=100))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://r") as c:
        assert (await c.post("/webhooks/alpha", content=b"x" * 101)).status_code == 413


# --------------------------------------------------------------------------- reading data
async def test_health_checks_the_database(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_events_endpoint_filters_and_paginates(client, make_generator):
    total = await _fill(client, make_generator, shipments=10)
    page = await _events(client, limit=4)
    assert len(page) == 4
    rest = await _events(client, after_id=page[-1]["id"])
    assert len(page) + len(rest) == total

    tracking = page[0]["tracking_number"]
    only = await _events(client, tracking_number=tracking)
    assert only and {r["tracking_number"] for r in only} == {tracking}


async def test_events_endpoint_validates_its_parameters(client):
    assert (await client.get("/events", params={"limit": 0})).status_code == 422
    assert (await client.get("/events", params={"limit": 5000})).status_code == 422
    assert (await client.get("/events", params={"after_id": -1})).status_code == 422


async def test_stats_endpoint(client, make_generator):
    await _fill(client, make_generator)
    stats = (await client.get("/stats")).json()
    assert stats["unique_events"] == stats["total_deliveries"] > 0
    assert stats["duplicates"] == 0 and stats["rejected"] == 0


# ----------------------------------------------------------------------------- extraction
async def test_ndjson_export_matches_the_events_endpoint(client, make_generator):
    total = await _fill(client, make_generator, shipments=8)
    response = await client.get("/exports/events.ndjson")
    assert response.headers["content-type"].startswith("application/x-ndjson")
    rows = _lines(response)
    assert len(rows) == total
    assert rows == await _events(client)


async def test_ndjson_export_supports_incremental_pulls(client, make_generator):
    await _fill(client, make_generator, shipments=6)
    everything = _lines(await client.get("/exports/events.ndjson"))
    cursor = everything[9]["id"]
    tail = _lines(await client.get("/exports/events.ndjson", params={"after_id": cursor}))
    assert tail == everything[10:]


async def test_exports_can_be_filtered_by_carrier(client, make_generator):
    await _fill(client, make_generator, shipments=30)
    rows = _lines(await client.get("/exports/events.ndjson", params={"carrier": "delta"}))
    assert rows and {r["carrier"] for r in rows} == {"delta"}


async def test_csv_export_round_trips_including_awkward_bodies(client, make_generator):
    await _fill(client, make_generator, shipments=8)  # includes XML bodies with newlines/quotes
    response = await client.get("/exports/events.csv")
    assert "attachment" in response.headers["content-disposition"]
    parsed = list(csv.DictReader(io.StringIO(response.text)))
    expected = await _events(client)
    assert tuple(parsed[0]) == EVENT_COLUMNS
    assert [row["raw_body"] for row in parsed] == [row["raw_body"] for row in expected]
    assert [int(row["id"]) for row in parsed] == [row["id"] for row in expected]


async def test_exports_of_an_empty_database_are_valid(client):
    assert (await client.get("/exports/events.ndjson")).text == ""
    assert (await client.get("/exports/events.csv")).text.strip() == ",".join(EVENT_COLUMNS)
