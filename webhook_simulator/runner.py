"""Bucle principal: genera lotes de eventos, inyecta duplicados/desorden y los envía por HTTP (push)."""

import asyncio
import json
import logging
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import TextIO

import httpx

from webhook_simulator import __version__
from webhook_simulator.catalog import CARRIERS_BY_SLUG
from webhook_simulator.chaos import Delivery, plan_deliveries, summarize
from webhook_simulator.config import Settings
from webhook_simulator.formats import encode
from webhook_simulator.generator import EventGenerator

log = logging.getLogger("webhook_simulator")
USER_AGENT = f"carrier-webhook-simulator/{__version__}"


@dataclass
class RunStats:
    sent: int = 0  # mensajes enviados (o mostrados en dry-run)
    delivered: int = 0  # respuestas 2xx
    failed: int = 0  # errores de red o respuestas no 2xx
    unique_events: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    per_carrier: Counter = field(default_factory=Counter)
    per_status: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {
            "sent": self.sent,
            "delivered": self.delivered,
            "failed": self.failed,
            "unique_events": self.unique_events,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "per_carrier": dict(sorted(self.per_carrier.items())),
            "distinct_statuses": len(self.per_status),
        }


async def _push(client: httpx.AsyncClient, delivery: Delivery, settings: Settings, stats: RunStats) -> None:
    event = delivery.event
    request = encode(CARRIERS_BY_SLUG[event.carrier].payload_format, event)
    url = settings.target_url_template.format(carrier=event.carrier)
    try:
        response = await client.post(
            url,
            content=request.body,
            headers={"Content-Type": request.content_type, "User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        stats.failed += 1
        _log_failure(stats, f"{event.carrier}: no se pudo enviar a {url} ({exc.__class__.__name__})")
        return
    if response.is_success:
        stats.delivered += 1
    else:
        stats.failed += 1
        _log_failure(stats, f"{event.carrier}: {url} respondió {response.status_code}")


def _log_failure(stats: RunStats, message: str) -> None:
    # Se avisan los primeros fallos y luego uno de cada 50, para no inundar el log.
    if stats.failed <= 5 or stats.failed % 50 == 0:
        log.warning("%s (fallos hasta ahora: %d)", message, stats.failed)


def _show(delivery: Delivery, settings: Settings, out: TextIO) -> None:
    event = delivery.event
    request = encode(CARRIERS_BY_SLUG[event.carrier].payload_format, event)
    out.write(
        json.dumps(
            {
                "carrier": event.carrier,
                "url": settings.target_url_template.format(carrier=event.carrier),
                "content_type": request.content_type,
                "duplicate": delivery.duplicate,
                "body": request.body.decode("utf-8"),
            },
            ensure_ascii=False,
        )
        + "\n"
    )


async def run(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    stop: asyncio.Event | None = None,
    out: TextIO | None = None,
    clock=None,
) -> RunStats:
    """Envía lotes hasta llegar a max_events (o hasta que `stop` se active, o sin fin si es 0)."""
    rng = random.Random(settings.seed)
    profiles = [CARRIERS_BY_SLUG[slug] for slug in settings.carriers]
    generator = EventGenerator(profiles, rng, **({"clock": clock} if clock else {}))
    stop = stop or asyncio.Event()
    out = out or sys.stdout
    stats = RunStats()

    owns_client = client is None and not settings.dry_run
    if owns_client:
        client = httpx.AsyncClient(timeout=settings.timeout)
    try:
        while not stop.is_set() and (settings.max_events == 0 or stats.sent < settings.max_events):
            plan = plan_deliveries(generator.new_batch(settings.shipments_per_batch), settings.chaos, rng)
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
                if settings.dry_run:
                    _show(delivery, settings, out)
                else:
                    await _push(client, delivery, settings, stats)
                if settings.rate > 0:
                    await asyncio.sleep(1 / settings.rate)
            # Las cifras de duplicados y desorden cuentan solo lo que realmente se envió.
            batch = summarize(plan[:sent_in_batch])
            stats.unique_events += batch.unique
            stats.duplicates += batch.duplicates
            stats.out_of_order += batch.out_of_order
            log.info(
                "lote enviado: %d mensajes (%d duplicados, %d fuera de orden) | total %d",
                batch.total, batch.duplicates, batch.out_of_order, stats.sent,
            )
    finally:
        if owns_client:
            await client.aclose()
    return stats
