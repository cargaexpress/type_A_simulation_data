"""Formatos de mensaje: cada transportadora serializa el mismo evento de forma distinta (RIWI-83)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from webhook_simulator.generator import ShipmentEvent

BOGOTA = timezone(timedelta(hours=-5))


@dataclass(frozen=True)
class EncodedRequest:
    body: bytes
    content_type: str


def _json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def json_flat(event: ShipmentEvent) -> EncodedRequest:
    """JSON plano en snake_case, hora ISO-8601 en UTC."""
    return EncodedRequest(
        _json(
            {
                "event_id": event.event_id,
                "tracking_number": event.tracking_number,
                "status": event.status.raw,
                "occurred_at": event.occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "location": event.location,
            }
        ),
        "application/json",
    )


def json_nested(event: ShipmentEvent) -> EncodedRequest:
    """JSON anidado en camelCase, código de estado numérico y hora en milisegundos desde 1970."""
    return EncodedRequest(
        _json(
            {
                "eventId": event.event_id,
                "shipment": {"trackingId": event.tracking_number},
                "event": {
                    "code": event.status.raw,
                    "occurredAtEpochMs": int(event.occurred_at.timestamp() * 1000),
                },
                "hub": event.location,
            }
        ),
        "application/json",
    )


def json_es(event: ShipmentEvent) -> EncodedRequest:
    """JSON en español, estado en texto y hora local de Colombia (-05:00)."""
    return EncodedRequest(
        _json(
            {
                "id_evento": event.event_id,
                "guia": event.tracking_number,
                "estado": event.status.raw,
                "fecha": event.occurred_at.astimezone(BOGOTA).isoformat(timespec="seconds"),
                "ciudad": event.location,
            }
        ),
        "application/json; charset=utf-8",
    )


def xml(event: ShipmentEvent) -> EncodedRequest:
    """XML con códigos cortos de estado y hora compacta en UTC."""
    root = ET.Element("ShipmentEvent", {"id": event.event_id})
    ET.SubElement(root, "Tracking").text = event.tracking_number
    ET.SubElement(root, "Status").text = event.status.raw
    ET.SubElement(root, "Timestamp").text = event.occurred_at.strftime("%Y%m%dT%H%M%SZ")
    ET.SubElement(root, "Location").text = event.location
    return EncodedRequest(
        ET.tostring(root, encoding="utf-8", xml_declaration=True), "application/xml"
    )


def form(event: ShipmentEvent) -> EncodedRequest:
    """Formulario clásico (x-www-form-urlencoded), estado descriptivo y hora en segundos desde 1970."""
    return EncodedRequest(
        urlencode(
            {
                "evt": event.event_id,
                "awb": event.tracking_number,
                "state": event.status.raw,
                "ts": int(event.occurred_at.timestamp()),
                "city": event.location,
            }
        ).encode("ascii"),
        "application/x-www-form-urlencoded",
    )


FORMATS: dict[str, Callable[[ShipmentEvent], EncodedRequest]] = {
    "json_flat": json_flat,
    "json_nested": json_nested,
    "json_es": json_es,
    "xml": xml,
    "form": form,
}


def encode(payload_format: str, event: ShipmentEvent) -> EncodedRequest:
    return FORMATS[payload_format](event)
