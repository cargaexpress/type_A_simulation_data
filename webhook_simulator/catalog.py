"""Catálogo de transportadoras Tipo A y de sus estados propios (RIWI-84).

Cada transportadora tiene su propio vocabulario de estados (lo que realmente
manda por webhook) y un formato de mensaje distinto (ver formats.py).

`canonical` indica a qué estado del sistema debería traducirse cada estado: sirve
para armar recorridos de envío realistas y para documentar el mapeo esperado.
Alpha, Beta y Gamma usan exactamente los mismos estados y traducciones que el seed
de la tabla `state_mapping` del backend (migración c4a1209b7e6f), de modo que sus
eventos se pueden traducir con el mapeo ya existente.
"""

from dataclasses import dataclass

# Espejo de CANONICAL_STATUSES de backend/app/models/state_mapping.py.
CANONICAL_STATUSES: tuple[str, ...] = (
    "CREATED",
    "PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "EXCEPTION",
    "DELIVERED",
    "RETURNED",
    "LOST_OR_DAMAGED",
)


@dataclass(frozen=True)
class CarrierStatus:
    raw: str  # texto exacto que envía la transportadora
    canonical: str  # estado del sistema al que debe traducirse
    cancel: bool = False  # cancelación: solo ocurre al inicio, nunca a mitad del recorrido


@dataclass(frozen=True)
class CarrierProfile:
    slug: str  # se usa en la URL de destino: .../webhooks/<slug>
    name: str  # nombre en la tabla carriers
    payload_format: str  # clave de formats.FORMATS
    tracking_prefix: str
    statuses: tuple[CarrierStatus, ...]

    def statuses_for(self, canonical: str, *, cancel: bool = False) -> tuple[CarrierStatus, ...]:
        return tuple(s for s in self.statuses if s.canonical == canonical and s.cancel == cancel)


def _s(raw: str, canonical: str, cancel: bool = False) -> CarrierStatus:
    return CarrierStatus(raw=raw, canonical=canonical, cancel=cancel)


ALPHA = CarrierProfile(
    slug="alpha",
    name="SimCarrier Alpha",
    payload_format="json_flat",
    tracking_prefix="ALP",
    statuses=(
        _s("CREATED", "CREATED"),
        _s("PICKED_UP", "PICKED_UP"),
        _s("IN_TRANSIT", "IN_TRANSIT"),
        _s("OUT_FOR_DELIVERY", "OUT_FOR_DELIVERY"),
        _s("DELIVERED", "DELIVERED"),
        _s("DELIVERY_ATTEMPT_FAILED", "EXCEPTION"),
        _s("HELD_AT_CUSTOMS", "EXCEPTION"),
        _s("CANCELLED", "EXCEPTION", cancel=True),
        _s("RETURNED_TO_SENDER", "RETURNED"),
        _s("LOST_OR_DAMAGED", "LOST_OR_DAMAGED"),
    ),
)

BETA = CarrierProfile(
    slug="beta",
    name="SimCarrier Beta",
    payload_format="json_nested",
    tracking_prefix="BET",
    statuses=(
        _s("100", "CREATED"),
        _s("200", "PICKED_UP"),
        _s("300", "IN_TRANSIT"),
        _s("400", "OUT_FOR_DELIVERY"),
        _s("500", "DELIVERED"),
        _s("600", "EXCEPTION"),
        _s("900", "EXCEPTION"),
        _s("800", "EXCEPTION", cancel=True),
        _s("700", "RETURNED"),
        _s("999", "LOST_OR_DAMAGED"),
    ),
)

GAMMA = CarrierProfile(
    slug="gamma",
    name="SimCarrier Gamma",
    payload_format="json_es",
    tracking_prefix="GAM",
    statuses=(
        _s("Generada", "CREATED"),
        _s("Recolectada", "PICKED_UP"),
        _s("En tránsito", "IN_TRANSIT"),
        _s("En reparto", "OUT_FOR_DELIVERY"),
        _s("Entregada", "DELIVERED"),
        _s("Intento fallido", "EXCEPTION"),
        _s("Novedad", "EXCEPTION"),
        _s("Cancelada", "EXCEPTION", cancel=True),
        _s("Devuelta al remitente", "RETURNED"),
        _s("Perdida o dañada", "LOST_OR_DAMAGED"),
    ),
)

DELTA = CarrierProfile(
    slug="delta",
    name="SimCarrier Delta",
    payload_format="xml",
    tracking_prefix="DEL",
    statuses=(
        _s("NEW", "CREATED"),
        _s("PCK", "PICKED_UP"),
        _s("TRN", "IN_TRANSIT"),
        _s("HUB", "IN_TRANSIT"),
        _s("OFD", "OUT_FOR_DELIVERY"),
        _s("DLV", "DELIVERED"),
        _s("NDL", "EXCEPTION"),
        _s("HLD", "EXCEPTION"),
        _s("CNL", "EXCEPTION", cancel=True),
        _s("RTS", "RETURNED"),
        _s("LST", "LOST_OR_DAMAGED"),
    ),
)

EPSILON = CarrierProfile(
    slug="epsilon",
    name="SimCarrier Epsilon",
    payload_format="form",
    tracking_prefix="EPS",
    statuses=(
        _s("Shipment registered", "CREATED"),
        _s("Collected from sender", "PICKED_UP"),
        _s("Departed origin facility", "IN_TRANSIT"),
        _s("Arrived at destination facility", "IN_TRANSIT"),
        _s("Out for delivery", "OUT_FOR_DELIVERY"),
        _s("Delivered to recipient", "DELIVERED"),
        _s("Delivery attempt unsuccessful", "EXCEPTION"),
        _s("Held - address verification", "EXCEPTION"),
        _s("Cancelled by shipper", "EXCEPTION", cancel=True),
        _s("Returned to shipper", "RETURNED"),
        _s("Lost or damaged in transit", "LOST_OR_DAMAGED"),
    ),
)

CARRIERS: tuple[CarrierProfile, ...] = (ALPHA, BETA, GAMMA, DELTA, EPSILON)
CARRIERS_BY_SLUG: dict[str, CarrierProfile] = {c.slug: c for c in CARRIERS}
