"""Generador de eventos aleatorios por transportadora (RIWI-83).

Cada envío (shipment) recorre un ciclo de vida realista: creado, recolectado,
en tránsito, en reparto y entregado, con variantes (novedades, devolución, pérdida,
cancelación). En cada paso se elige al azar uno de los estados propios de la
transportadora que corresponda, así se obtienen estados variados.
"""

import random
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from webhook_simulator.catalog import CarrierProfile, CarrierStatus

CITIES = (
    "Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena",
    "Bucaramanga", "Pereira", "Cúcuta", "Manizales", "Santa Marta",
)  # fmt: skip

# (peso, recorrido en estados canónicos). Los recorridos con EXCEPTION usan estados
# de novedad de la transportadora; "cancelación" usa su estado marcado como cancel.
LIFECYCLES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (55, ("CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED")),
    (15, ("CREATED", "PICKED_UP", "IN_TRANSIT", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED")),
    (10, ("CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "EXCEPTION", "OUT_FOR_DELIVERY", "DELIVERED")),
    (6, ("CREATED", "PICKED_UP", "IN_TRANSIT", "EXCEPTION", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED")),
    (6, ("CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "EXCEPTION", "RETURNED")),
    (4, ("CREATED", "PICKED_UP", "IN_TRANSIT", "LOST_OR_DAMAGED")),
    (4, ("CREATED", "CANCEL")),
)  # fmt: skip


@dataclass(frozen=True)
class ShipmentEvent:
    event_id: str
    carrier: str  # slug de la transportadora
    tracking_number: str
    status: CarrierStatus
    occurred_at: datetime  # UTC, en segundos exactos
    location: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventGenerator:
    def __init__(
        self,
        profiles: Sequence[CarrierProfile],
        rng: random.Random,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if not profiles:
            raise ValueError("Se necesita al menos una transportadora")
        self._profiles = tuple(profiles)
        self._rng = rng
        self._clock = clock
        self._used_tracking: set[str] = set()

    def _tracking_number(self, profile: CarrierProfile) -> str:
        while True:
            number = f"{profile.tracking_prefix}{self._rng.randrange(10**9, 10**10)}"
            if number not in self._used_tracking:
                self._used_tracking.add(number)
                return number

    def _event_id(self) -> str:
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))

    @staticmethod
    def _candidates(profile: CarrierProfile, step: str) -> tuple[CarrierStatus, ...]:
        """Estados de la transportadora que sirven para un paso del recorrido."""
        if step == "CANCEL":
            return tuple(s for s in profile.statuses if s.cancel)
        return profile.statuses_for(step)

    def _pick_lifecycle(self, profile: CarrierProfile) -> tuple[str, ...]:
        # Solo recorridos que esta transportadora puede expresar con sus estados.
        options = [
            (weight, path)
            for weight, path in LIFECYCLES
            if all(self._candidates(profile, step) for step in path)
        ]
        return self._rng.choices(
            [path for _, path in options], weights=[w for w, _ in options], k=1
        )[0]

    def new_shipment(self, profile: CarrierProfile | None = None) -> list[ShipmentEvent]:
        """Eventos de un envío, en el orden en que realmente ocurrieron."""
        profile = profile or self._rng.choice(self._profiles)
        path = self._pick_lifecycle(profile)
        tracking = self._tracking_number(profile)

        gaps = [self._rng.randint(5, 240) for _ in path]  # minutos entre un paso y el siguiente
        started = self._clock().replace(microsecond=0) - timedelta(
            minutes=sum(gaps) + self._rng.randint(0, 360)
        )
        events: list[ShipmentEvent] = []
        moment = started
        for step, gap in zip(path, gaps):
            moment += timedelta(minutes=gap)
            events.append(
                ShipmentEvent(
                    event_id=self._event_id(),
                    carrier=profile.slug,
                    tracking_number=tracking,
                    status=self._rng.choice(self._candidates(profile, step)),
                    occurred_at=moment,
                    location=self._rng.choice(CITIES),
                )
            )
        return events

    def new_batch(self, shipments: int) -> list[list[ShipmentEvent]]:
        return [self.new_shipment() for _ in range(shipments)]
