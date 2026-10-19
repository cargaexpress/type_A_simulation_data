"""Configurable duplicate and out-of-order events (RIWI-85).

We start from the "perfect" order (each shipment arrives in the order it happened, mixed
with the other shipments) and then mess it up using two independent probabilities:

- out_of_order_rate: chance that an event arrives AFTER a later event of the same shipment
  (e.g. "Delivered" shows up before "Out for delivery").
- duplicate_rate: chance that an event is re-sent identically (same id, same bytes), which
  is what carriers do when they retry a webhook.
"""

import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from webhook_simulator.domain.models import ShipmentEvent


@dataclass(frozen=True, slots=True)
class ChaosConfig:
    duplicate_rate: float = 0.0
    out_of_order_rate: float = 0.0
    duplicate_max_delay: int = 5  # a duplicate arrives at most this many messages later

    def __post_init__(self) -> None:
        for name in ("duplicate_rate", "out_of_order_rate"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1 (got {value})")
        if self.duplicate_max_delay < 0:
            raise ValueError("duplicate_max_delay cannot be negative")


@dataclass(frozen=True, slots=True)
class Delivery:
    event: ShipmentEvent
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class PlanStats:
    total: int  # messages to send (duplicates included)
    unique: int  # distinct events
    duplicates: int  # identical re-sends
    out_of_order: int  # events arriving after a later event of the same shipment


def _interleave(
    shipments: Sequence[Sequence[ShipmentEvent]], rng: random.Random
) -> list[ShipmentEvent]:
    """Mix shipments together without touching the internal order of each one."""
    tokens = [index for index, events in enumerate(shipments) for _ in events]
    rng.shuffle(tokens)
    cursors = [iter(events) for events in shipments]
    return [next(cursors[index]) for index in tokens]


def _make_out_of_order(sequence: list[ShipmentEvent], rate: float, rng: random.Random) -> None:
    """Swap an event with a later one from the same shipment (edits the list in place)."""
    touched: set[str] = set()
    for i in range(len(sequence)):
        event = sequence[i]
        if event.event_id in touched or rng.random() >= rate:
            continue
        later = [
            j
            for j in range(i + 1, len(sequence))
            if sequence[j].tracking_number == event.tracking_number
            and sequence[j].event_id not in touched
        ]
        if not later:
            continue
        j = rng.choice(later)
        sequence[i], sequence[j] = sequence[j], sequence[i]
        touched.update((sequence[i].event_id, sequence[j].event_id))


def _add_duplicates(
    sequence: Sequence[ShipmentEvent], rate: float, max_delay: int, rng: random.Random
) -> list[Delivery]:
    scheduled: dict[int, list[Delivery]] = defaultdict(list)
    for i, event in enumerate(sequence):
        if rng.random() < rate:
            scheduled[i + 1 + rng.randint(0, max_delay)].append(Delivery(event, duplicate=True))

    plan: list[Delivery] = []
    for i, event in enumerate(sequence):
        plan.extend(scheduled.pop(i, []))
        plan.append(Delivery(event))
    for position in sorted(scheduled):  # duplicates that land after the last message
        plan.extend(scheduled[position])
    return plan


def plan_deliveries(
    shipments: Sequence[Sequence[ShipmentEvent]], chaos: ChaosConfig, rng: random.Random
) -> list[Delivery]:
    """Final sending order for a batch of shipments, with disorder and duplicates injected."""
    sequence = _interleave(shipments, rng)
    _make_out_of_order(sequence, chaos.out_of_order_rate, rng)
    return _add_duplicates(sequence, chaos.duplicate_rate, chaos.duplicate_max_delay, rng)


def summarize(plan: Sequence[Delivery]) -> PlanStats:
    latest_seen: dict[str, ShipmentEvent] = {}
    out_of_order = duplicates = 0
    for delivery in plan:
        if delivery.duplicate:
            duplicates += 1
            continue
        event = delivery.event
        newest = latest_seen.get(event.tracking_number)
        if newest is not None and newest.occurred_at > event.occurred_at:
            out_of_order += 1
        if newest is None or event.occurred_at > newest.occurred_at:
            latest_seen[event.tracking_number] = event
    return PlanStats(
        total=len(plan),
        unique=len(plan) - duplicates,
        duplicates=duplicates,
        out_of_order=out_of_order,
    )
