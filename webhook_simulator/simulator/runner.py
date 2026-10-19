"""Main loop: build batches, inject duplicates/disorder, push them out at a steady pace."""

import asyncio
import contextlib
import logging
import random
from collections.abc import Callable
from datetime import datetime

from webhook_simulator.domain.catalog import CARRIERS_BY_SLUG
from webhook_simulator.domain.chaos import plan_deliveries, summarize
from webhook_simulator.domain.generator import EventGenerator
from webhook_simulator.simulator.config import SimulatorSettings
from webhook_simulator.simulator.sender import Sender
from webhook_simulator.simulator.stats import RunStats

log = logging.getLogger("webhook_simulator")


def _log_failure(stats: RunStats, message: str) -> None:
    # Shout about the first few failures, then only every 50th, so the log stays readable.
    if stats.failed <= 5 or stats.failed % 50 == 0:
        log.warning("%s (failures so far: %d)", message, stats.failed)


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake up immediately if somebody asks us to stop."""
    if seconds <= 0:
        return
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def run(
    settings: SimulatorSettings,
    sender: Sender,
    *,
    stop: asyncio.Event | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RunStats:
    """Send batches until `max_events` is reached, `stop` is set, or forever if max_events=0."""
    rng = random.Random(settings.seed)
    profiles = [CARRIERS_BY_SLUG[slug] for slug in settings.carrier_slugs]
    generator = EventGenerator(profiles, rng, clock=clock)
    stop = stop or asyncio.Event()
    stats = RunStats()

    loop = asyncio.get_running_loop()
    interval = 1 / settings.rate if settings.rate > 0 else 0.0
    next_slot = loop.time()  # fixed schedule, so the REAL rate matches the configured one

    while not stop.is_set() and (settings.max_events == 0 or stats.sent < settings.max_events):
        plan = plan_deliveries(
            generator.new_batch(settings.shipments_per_batch), settings.chaos, rng
        )
        if settings.max_events:
            plan = plan[: settings.max_events - stats.sent]
        sent_in_batch = 0

        for delivery in plan:
            if stop.is_set():
                break
            sent_in_batch += 1
            stats.sent += 1
            stats.per_carrier[delivery.event.carrier] += 1
            stats.per_status[(delivery.event.carrier, delivery.event.status.raw)] += 1

            result = await sender.send(delivery)
            if result.delivered:
                stats.delivered += 1
            else:
                stats.failed += 1
                _log_failure(stats, f"{delivery.event.carrier}: {result.error}")

            await asyncio.sleep(0)  # always give signal handlers a chance, even at rate 0
            if interval:
                # If we fell behind (slow receiver), restart the schedule instead of bursting.
                next_slot = max(next_slot + interval, loop.time())
                await _pause(stop, next_slot - loop.time())

        # Duplicate/disorder numbers only count what was REALLY sent (a stop can cut a batch).
        batch = summarize(plan[:sent_in_batch])
        stats.unique_events += batch.unique
        stats.duplicates += batch.duplicates
        stats.out_of_order += batch.out_of_order
        log.info(
            "batch sent: %d messages (%d duplicates, %d out of order) | total %d",
            batch.total, batch.duplicates, batch.out_of_order, stats.sent,
        )  # fmt: skip
    return stats
