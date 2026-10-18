"""Inyección configurable de eventos duplicados y fuera de orden (RIWI-85).

Parte del orden "perfecto" (cada envío llega en el orden en que ocurrió, mezclado con
los demás envíos) y lo desordena según dos probabilidades independientes:

- out_of_order_rate: probabilidad de que un evento llegue DESPUÉS de uno posterior del
  mismo envío (por ejemplo, "Entregada" antes de "En reparto").
- duplicate_rate: probabilidad de que un evento se reenvíe idéntico (mismo id y mismo
  contenido), como hacen las transportadoras al reintentar un webhook.
"""

import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from webhook_simulator.generator import ShipmentEvent


@dataclass(frozen=True)
class ChaosConfig:
    duplicate_rate: float = 0.0
    out_of_order_rate: float = 0.0
    duplicate_max_delay: int = 5  # un duplicado llega, como máximo, tantos mensajes después

    def __post_init__(self) -> None:
        for name in ("duplicate_rate", "out_of_order_rate"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} debe estar entre 0 y 1 (recibido: {value})")
        if self.duplicate_max_delay < 0:
            raise ValueError("duplicate_max_delay no puede ser negativo")


@dataclass(frozen=True)
class Delivery:
    event: ShipmentEvent
    duplicate: bool = False


@dataclass(frozen=True)
class PlanStats:
    total: int  # mensajes a enviar (incluye duplicados)
    unique: int  # eventos distintos
    duplicates: int  # reenvíos idénticos
    out_of_order: int  # eventos que llegan después de uno posterior de su mismo envío


def _interleave(shipments: Sequence[Sequence[ShipmentEvent]], rng: random.Random) -> list[ShipmentEvent]:
    """Mezcla los envíos entre sí sin alterar el orden interno de cada uno."""
    tokens = [index for index, events in enumerate(shipments) for _ in events]
    rng.shuffle(tokens)
    cursors = [iter(events) for events in shipments]
    return [next(cursors[index]) for index in tokens]


def _make_out_of_order(sequence: list[ShipmentEvent], rate: float, rng: random.Random) -> None:
    """Intercambia un evento con uno posterior de su mismo envío (modifica la lista)."""
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
    for position in sorted(scheduled):  # duplicados que caen después del último mensaje
        plan.extend(scheduled[position])
    return plan


def plan_deliveries(
    shipments: Sequence[Sequence[ShipmentEvent]], chaos: ChaosConfig, rng: random.Random
) -> list[Delivery]:
    """Orden final de envío de un lote de envíos, con desorden y duplicados inyectados."""
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
