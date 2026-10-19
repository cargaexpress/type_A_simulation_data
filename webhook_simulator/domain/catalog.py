"""Catalog of the Type A carriers and their own status vocabularies (RIWI-84).

Every carrier speaks its own language: its own status names AND its own message format
(see `webhook_simulator/formats`). `canonical` says which of OUR statuses each carrier
status should be translated to. We use it to build realistic shipment journeys and to
document the mapping the backend is expected to apply.

Alpha, Beta and Gamma use exactly the same states and translations as the backend's
`state_mapping` seed (migration c4a1209b7e6f), so their events can be translated with the
mapping that already exists. Delta and Epsilon are new carriers.

Note: Gamma's statuses are in Spanish on purpose. That's what the carrier really sends,
and the backend mapping matches on those exact strings, so they must NOT be translated.
"""

from dataclasses import dataclass
from enum import StrEnum


class CanonicalStatus(StrEnum):
    """Our internal statuses (mirror of CANONICAL_STATUSES in the backend)."""

    CREATED = "CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    EXCEPTION = "EXCEPTION"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    LOST_OR_DAMAGED = "LOST_OR_DAMAGED"


class PayloadFormat(StrEnum):
    """The five message formats. Each one has an encoder and a decoder."""

    JSON_FLAT = "json_flat"
    JSON_NESTED = "json_nested"
    JSON_ES = "json_es"
    XML = "xml"
    FORM = "form"


@dataclass(frozen=True, slots=True)
class CarrierStatus:
    raw: str  # exact text the carrier sends
    canonical: CanonicalStatus  # our status it should be translated to
    cancel: bool = False  # cancellations only happen at the start, never mid-journey


@dataclass(frozen=True, slots=True)
class CarrierProfile:
    slug: str  # used in the target URL: .../webhooks/<slug>
    name: str  # name in the backend's carriers table
    payload_format: PayloadFormat
    tracking_prefix: str
    statuses: tuple[CarrierStatus, ...]

    def statuses_for(
        self, canonical: CanonicalStatus | str, *, cancel: bool = False
    ) -> tuple[CarrierStatus, ...]:
        """Carrier statuses that translate to `canonical` (optionally only the cancel ones)."""
        return tuple(s for s in self.statuses if s.canonical == canonical and s.cancel == cancel)

    def canonical_for(self, raw_status: str) -> CanonicalStatus | None:
        """Translate a raw carrier status into ours. None means "never heard of it"."""
        return next((s.canonical for s in self.statuses if s.raw == raw_status), None)


def _s(raw: str, canonical: CanonicalStatus, cancel: bool = False) -> CarrierStatus:
    return CarrierStatus(raw=raw, canonical=canonical, cancel=cancel)


C = CanonicalStatus  # short alias, keeps the tables below readable

ALPHA = CarrierProfile(
    slug="alpha",
    name="SimCarrier Alpha",
    payload_format=PayloadFormat.JSON_FLAT,
    tracking_prefix="ALP",
    statuses=(
        _s("CREATED", C.CREATED),
        _s("PICKED_UP", C.PICKED_UP),
        _s("IN_TRANSIT", C.IN_TRANSIT),
        _s("OUT_FOR_DELIVERY", C.OUT_FOR_DELIVERY),
        _s("DELIVERED", C.DELIVERED),
        _s("DELIVERY_ATTEMPT_FAILED", C.EXCEPTION),
        _s("HELD_AT_CUSTOMS", C.EXCEPTION),
        _s("CANCELLED", C.EXCEPTION, cancel=True),
        _s("RETURNED_TO_SENDER", C.RETURNED),
        _s("LOST_OR_DAMAGED", C.LOST_OR_DAMAGED),
    ),
)

BETA = CarrierProfile(
    slug="beta",
    name="SimCarrier Beta",
    payload_format=PayloadFormat.JSON_NESTED,
    tracking_prefix="BET",
    statuses=(
        _s("100", C.CREATED),
        _s("200", C.PICKED_UP),
        _s("300", C.IN_TRANSIT),
        _s("400", C.OUT_FOR_DELIVERY),
        _s("500", C.DELIVERED),
        _s("600", C.EXCEPTION),
        _s("900", C.EXCEPTION),
        _s("800", C.EXCEPTION, cancel=True),
        _s("700", C.RETURNED),
        _s("999", C.LOST_OR_DAMAGED),
    ),
)

GAMMA = CarrierProfile(
    slug="gamma",
    name="SimCarrier Gamma",
    payload_format=PayloadFormat.JSON_ES,
    tracking_prefix="GAM",
    statuses=(
        _s("Generada", C.CREATED),
        _s("Recolectada", C.PICKED_UP),
        _s("En tránsito", C.IN_TRANSIT),
        _s("En reparto", C.OUT_FOR_DELIVERY),
        _s("Entregada", C.DELIVERED),
        _s("Intento fallido", C.EXCEPTION),
        _s("Novedad", C.EXCEPTION),
        _s("Cancelada", C.EXCEPTION, cancel=True),
        _s("Devuelta al remitente", C.RETURNED),
        _s("Perdida o dañada", C.LOST_OR_DAMAGED),
    ),
)

DELTA = CarrierProfile(
    slug="delta",
    name="SimCarrier Delta",
    payload_format=PayloadFormat.XML,
    tracking_prefix="DEL",
    statuses=(
        _s("NEW", C.CREATED),
        _s("PCK", C.PICKED_UP),
        _s("TRN", C.IN_TRANSIT),
        _s("HUB", C.IN_TRANSIT),
        _s("OFD", C.OUT_FOR_DELIVERY),
        _s("DLV", C.DELIVERED),
        _s("NDL", C.EXCEPTION),
        _s("HLD", C.EXCEPTION),
        _s("CNL", C.EXCEPTION, cancel=True),
        _s("RTS", C.RETURNED),
        _s("LST", C.LOST_OR_DAMAGED),
    ),
)

EPSILON = CarrierProfile(
    slug="epsilon",
    name="SimCarrier Epsilon",
    payload_format=PayloadFormat.FORM,
    tracking_prefix="EPS",
    statuses=(
        _s("Shipment registered", C.CREATED),
        _s("Collected from sender", C.PICKED_UP),
        _s("Departed origin facility", C.IN_TRANSIT),
        _s("Arrived at destination facility", C.IN_TRANSIT),
        _s("Out for delivery", C.OUT_FOR_DELIVERY),
        _s("Delivered to recipient", C.DELIVERED),
        _s("Delivery attempt unsuccessful", C.EXCEPTION),
        _s("Held - address verification", C.EXCEPTION),
        _s("Cancelled by shipper", C.EXCEPTION, cancel=True),
        _s("Returned to shipper", C.RETURNED),
        _s("Lost or damaged in transit", C.LOST_OR_DAMAGED),
    ),
)

CARRIERS: tuple[CarrierProfile, ...] = (ALPHA, BETA, GAMMA, DELTA, EPSILON)
CARRIERS_BY_SLUG: dict[str, CarrierProfile] = {c.slug: c for c in CARRIERS}
