"""Random event generator, one journey per shipment (RIWI-83).

Each shipment follows a realistic life cycle (created, picked up, in transit, out for
delivery, delivered) with variants (exceptions, return, loss, cancellation). At every step
we randomly pick one of the carrier's OWN statuses that fits, so statuses vary a lot.
"""

import random
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from webhook_simulator.domain.catalog import CanonicalStatus, CarrierProfile, CarrierStatus
from webhook_simulator.domain.models import ShipmentEvent

CITIES = (
    "Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena",
    "Bucaramanga", "Pereira", "Cúcuta", "Manizales", "Santa Marta",
)  # fmt: skip

CANCEL_STEP = "CANCEL"  # pseudo-step: "use whatever status this carrier has for cancelling"

C = CanonicalStatus

# (weight, journey as canonical steps). Journeys with EXCEPTION pick one of the carrier's
# exception statuses; CANCEL picks its status flagged as `cancel`.
LIFECYCLES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (55, (C.CREATED, C.PICKED_UP, C.IN_TRANSIT, C.OUT_FOR_DELIVERY, C.DELIVERED)),
    (15, (C.CREATED, C.PICKED_UP, C.IN_TRANSIT, C.IN_TRANSIT, C.OUT_FOR_DELIVERY, C.DELIVERED)),
    (10, (C.CREATED, C.PICKED_UP, C.IN_TRANSIT, C.OUT_FOR_DELIVERY, C.EXCEPTION,
          C.OUT_FOR_DELIVERY, C.DELIVERED)),
    (6, (C.CREATED, C.PICKED_UP, C.IN_TRANSIT, C.EXCEPTION, C.IN_TRANSIT,
         C.OUT_FOR_DELIVERY, C.DELIVERED)),
    (6, (C.CREATED, C.PICKED_UP, C.IN_TRANSIT, C.OUT_FOR_DELIVERY, C.EXCEPTION, C.RETURNED)),
    (4, (C.CREATED, C.PICKED_UP, C.IN_TRANSIT, C.LOST_OR_DAMAGED)),
    (4, (C.CREATED, CANCEL_STEP)),
)  # fmt: skip


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EventGenerator:
    def __init__(
        self,
        profiles: Sequence[CarrierProfile],
        rng: random.Random,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not profiles:
            raise ValueError("At least one carrier is required")
        self._profiles = tuple(profiles)
        self._rng = rng
        self._clock = clock or _utcnow  # injectable so tests get deterministic timestamps
        self._used_tracking: set[str] = set()

    def _tracking_number(self, profile: CarrierProfile) -> str:
        while True:
            number = f"{profile.tracking_prefix}{self._rng.randrange(10**9, 10**10)}"
            if number not in self._used_tracking:
                self._used_tracking.add(number)
                return number

    def _event_id(self) -> str:
        # Built from the seeded rng (not uuid4()) so the same seed gives the same ids.
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))

    @staticmethod
    def _candidates(profile: CarrierProfile, step: str) -> tuple[CarrierStatus, ...]:
        """Carrier statuses that can express one step of a journey."""
        if step == CANCEL_STEP:
            return tuple(s for s in profile.statuses if s.cancel)
        return profile.statuses_for(step)

    def _pick_lifecycle(self, profile: CarrierProfile) -> tuple[str, ...]:
        # Only journeys this carrier can actually express with its own statuses.
        options = [
            (weight, path)
            for weight, path in LIFECYCLES
            if all(self._candidates(profile, step) for step in path)
        ]
        return self._rng.choices(
            [path for _, path in options], weights=[w for w, _ in options], k=1
        )[0]

    def new_shipment(self, profile: CarrierProfile | None = None) -> list[ShipmentEvent]:
        """Events of one shipment, in the order they really happened."""
        profile = profile or self._rng.choice(self._profiles)
        path = self._pick_lifecycle(profile)
        tracking = self._tracking_number(profile)

        gaps = [self._rng.randint(5, 240) for _ in path]  # minutes between steps
        started = self._clock().replace(microsecond=0) - timedelta(
            minutes=sum(gaps) + self._rng.randint(0, 360)
        )
        events: list[ShipmentEvent] = []
        moment = started
        for step, gap in zip(path, gaps, strict=True):
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
