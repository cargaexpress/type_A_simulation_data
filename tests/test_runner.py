"""The simulator loop, tested with fake senders (no network)."""

import asyncio
import io
import json
import time
from collections import Counter

import httpx

from webhook_simulator.domain.catalog import CARRIERS_BY_SLUG
from webhook_simulator.formats import decode
from webhook_simulator.simulator.config import SimulatorSettings
from webhook_simulator.simulator.runner import run
from webhook_simulator.simulator.sender import DryRunSender, HttpSender, SendResult


class RecordingSender:
    """Remembers every delivery; can be told to fail."""

    def __init__(self, *, ok=True):
        self.ok = ok
        self.seen = []

    async def send(self, delivery):
        self.seen.append(delivery)
        return SendResult(self.ok, None if self.ok else "boom")


def _settings(**overrides):
    base = {
        "rate": 0, "max_events": 200, "seed": 3,
        "target_url_template": "http://t/webhooks/{carrier}",
    }  # fmt: skip
    return SimulatorSettings(**(base | overrides))


async def test_sends_exactly_max_events():
    sender = RecordingSender()
    stats = await run(_settings(), sender)
    assert len(sender.seen) == stats.sent == stats.delivered == 200 and stats.failed == 0


async def test_all_five_carriers_and_many_statuses_show_up():
    sender = RecordingSender()
    await run(_settings(max_events=1500), sender)
    statuses = {slug: set() for slug in CARRIERS_BY_SLUG}
    for delivery in sender.seen:
        statuses[delivery.event.carrier].add(delivery.event.status.raw)
    assert all(len(found) >= 6 for found in statuses.values())


async def test_real_duplicates_and_disorder_are_injected():
    sender = RecordingSender()
    stats = await run(_settings(duplicate_rate=0.3, out_of_order_rate=0.3, max_events=600), sender)
    ids = Counter(d.event.event_id for d in sender.seen)
    assert sum(count - 1 for count in ids.values()) == stats.duplicates > 0
    assert stats.out_of_order > 0


async def test_without_chaos_there_are_no_repeats():
    sender = RecordingSender()
    await run(_settings(duplicate_rate=0, out_of_order_rate=0, max_events=300), sender)
    assert len({d.event.event_id for d in sender.seen}) == len(sender.seen)


async def test_stats_add_up():
    sender = RecordingSender()
    stats = await run(_settings(duplicate_rate=0.3, out_of_order_rate=0.3, max_events=400), sender)
    assert stats.unique_events + stats.duplicates == stats.sent == 400


async def test_failures_are_counted_and_do_not_stop_the_run():
    stats = await run(_settings(max_events=20), RecordingSender(ok=False))
    assert stats.sent == 20 and stats.failed == 20 and stats.delivered == 0


async def test_same_seed_same_sequence():
    from datetime import UTC, datetime

    fixed = lambda: datetime(2026, 1, 1, tzinfo=UTC)  # noqa: E731
    a, b = io.StringIO(), io.StringIO()
    await run(_settings(seed=8), DryRunSender(a, "http://t/{carrier}"), clock=fixed)
    await run(_settings(seed=8), DryRunSender(b, "http://t/{carrier}"), clock=fixed)
    assert a.getvalue() == b.getvalue() != ""


async def test_stop_halts_an_endless_run_and_stats_only_count_what_was_sent():
    sender = RecordingSender()
    stop = asyncio.Event()
    task = asyncio.create_task(
        run(_settings(max_events=0, rate=200, shipments_per_batch=50), sender, stop=stop)
    )
    await asyncio.sleep(0.2)
    stop.set()
    stats = await asyncio.wait_for(task, 2)
    assert 0 < stats.sent == len(sender.seen)
    assert stats.unique_events + stats.duplicates == stats.sent


async def test_stop_wakes_up_a_slow_run_immediately():
    stop = asyncio.Event()
    task = asyncio.create_task(run(_settings(max_events=0, rate=0.1), RecordingSender(), stop=stop))
    await asyncio.sleep(0.1)
    started = time.monotonic()
    stop.set()
    await asyncio.wait_for(task, 2)  # at 0.1 msg/s a plain sleep would take 10 seconds
    assert time.monotonic() - started < 1


async def test_rate_is_respected():
    started = time.monotonic()
    await run(_settings(rate=50, max_events=25), RecordingSender())
    elapsed = time.monotonic() - started
    assert 0.4 < elapsed < 1.5  # 25 messages at 50/s ~ 0.5 s


async def test_dry_run_sender_prints_one_json_line_per_message():
    out = io.StringIO()
    stats = await run(_settings(max_events=30), DryRunSender(out, "http://t/webhooks/{carrier}"))
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert len(lines) == 30 == stats.sent
    assert {"carrier", "url", "content_type", "duplicate", "body"} <= set(lines[0])


# ------------------------------------------------------------------------------ HttpSender
def _http_sender(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpSender(client, "http://t/webhooks/{carrier}")


async def test_http_sender_posts_a_decodable_body_to_each_carriers_url():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200)

    stats = await run(_settings(max_events=150), _http_sender(handler))
    assert stats.delivered == 150
    assert {r.url.path for r in seen} == {f"/webhooks/{slug}" for slug in CARRIERS_BY_SLUG}
    for request in seen:
        carrier = CARRIERS_BY_SLUG[request.url.path.rsplit("/", 1)[1]]
        decode(carrier.payload_format, request.content)  # carrier's own format
        assert request.headers["user-agent"].startswith("carrier-webhook-simulator/")


async def test_http_sender_reports_error_responses_and_network_errors():
    bad_status = await run(_settings(max_events=10), _http_sender(lambda r: httpx.Response(500)))
    assert bad_status.failed == 10

    def boom(request):
        raise httpx.ConnectError("no connection")

    unreachable = await run(_settings(max_events=10), _http_sender(boom))
    assert unreachable.failed == 10 and unreachable.sent == 10
