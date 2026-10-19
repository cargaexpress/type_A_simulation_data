"""Encoders: each carrier serializes the same event in its own way (RIWI-83)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta, timezone
from urllib.parse import urlencode
from xml.etree import ElementTree as ET  # building XML is safe; only PARSING needs defusedxml

from webhook_simulator.domain.catalog import PayloadFormat
from webhook_simulator.domain.models import ShipmentEvent

BOGOTA = timezone(timedelta(hours=-5))  # Gamma sends local Colombian time


@dataclass(frozen=True, slots=True)
class EncodedRequest:
    body: bytes
    content_type: str


def _json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def json_flat(event: ShipmentEvent) -> EncodedRequest:
    """Flat JSON, snake_case, ISO-8601 time in UTC."""
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
    """Nested JSON, camelCase, numeric status code, time as milliseconds since 1970."""
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
    """Spanish JSON, text status, local Colombian time (-05:00)."""
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
    """XML with short status codes and compact UTC time."""
    root = ET.Element("ShipmentEvent", {"id": event.event_id})
    ET.SubElement(root, "Tracking").text = event.tracking_number
    ET.SubElement(root, "Status").text = event.status.raw
    ET.SubElement(root, "Timestamp").text = event.occurred_at.strftime("%Y%m%dT%H%M%SZ")
    ET.SubElement(root, "Location").text = event.location
    return EncodedRequest(
        ET.tostring(root, encoding="utf-8", xml_declaration=True), "application/xml"
    )


def form(event: ShipmentEvent) -> EncodedRequest:
    """Classic form post (x-www-form-urlencoded), descriptive status, time in epoch seconds."""
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


ENCODERS: dict[PayloadFormat, Callable[[ShipmentEvent], EncodedRequest]] = {
    PayloadFormat.JSON_FLAT: json_flat,
    PayloadFormat.JSON_NESTED: json_nested,
    PayloadFormat.JSON_ES: json_es,
    PayloadFormat.XML: xml,
    PayloadFormat.FORM: form,
}
