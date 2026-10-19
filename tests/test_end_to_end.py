"""Simulator -> receiver, wired together in-process. This is the HU-17 story, end to end."""

import httpx

from webhook_simulator.domain.catalog import CARRIERS_BY_SLUG
from webhook_simulator.simulator.config import SimulatorSettings
from webhook_simulator.simulator.runner import run
from webhook_simulator.simulator.sender import HttpSender


async def _simulate(app, **overrides):
    settings = SimulatorSettings(
        **(
            {
                "rate": 0,
                "seed": 11,
                "max_events": 600,
                "duplicate_rate": 0.2,
                "out_of_order_rate": 0.2,
                "target_url_template": "http://receiver/webhooks/{carrier}",
            }
            | overrides
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport) as client:
        stats = await run(settings, HttpSender(client, settings.target_url_template))
        return stats, (await client.get("http://receiver/stats")).json()


async def test_what_the_simulator_sent_is_exactly_what_the_receiver_stored(app):
    stats, received = await _simulate(app)

    assert stats.failed == 0 and stats.delivered == stats.sent == 600
    # Both sides count the same things independently, and they must agree.
    assert received["total_deliveries"] == stats.sent
    assert received["unique_events"] == stats.unique_events
    assert received["duplicates"] == stats.duplicates > 0
    assert received["out_of_order"] == stats.out_of_order > 0
    assert received["rejected"] == 0


async def test_all_five_carriers_with_at_least_six_statuses_each_reach_the_receiver(app):
    _, received = await _simulate(app, max_events=1500, shipments_per_batch=40)
    assert set(received["per_carrier"]) == set(CARRIERS_BY_SLUG)
    assert all(c["distinct_statuses"] >= 6 for c in received["per_carrier"].values())


async def test_every_status_the_simulator_sends_can_be_translated_by_the_receiver(app):
    await _simulate(app, max_events=800)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://receiver") as client:
        rows = (await client.get("/events", params={"limit": 1000})).json()
    assert rows and all(row["canonical_status"] is not None for row in rows)


async def test_same_seed_produces_the_same_stored_data(tmp_path):
    from datetime import UTC, datetime

    from webhook_simulator.receiver.api import create_app
    from webhook_simulator.receiver.config import ReceiverSettings

    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    snapshots = []
    for name in ("a.db", "b.db"):
        app = create_app(ReceiverSettings(db_path=str(tmp_path / name)), clock=lambda: fixed)
        settings = SimulatorSettings(
            rate=0, seed=5, max_events=200, target_url_template="http://r/webhooks/{carrier}"
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            await run(
                settings, HttpSender(client, settings.target_url_template),
                clock=lambda: fixed,
            )  # fmt: skip
            body = (await client.get("http://r/exports/events.ndjson")).text
        snapshots.append(body)
    assert snapshots[0] == snapshots[1] != ""
