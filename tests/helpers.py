"""Decodificadores independientes de cada formato (lo que haría el receptor de cada transportadora)."""
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs
from xml.etree import ElementTree as ET


def decode(payload_format, body: bytes) -> dict:
    """Devuelve event_id, tracking, status, occurred_at (UTC) y location."""
    if payload_format == "json_flat":
        d = json.loads(body)
        return dict(event_id=d["event_id"], tracking=d["tracking_number"], status=d["status"],
                    occurred_at=datetime.fromisoformat(d["occurred_at"].replace("Z", "+00:00")),
                    location=d["location"])
    if payload_format == "json_nested":
        d = json.loads(body)
        return dict(event_id=d["eventId"], tracking=d["shipment"]["trackingId"], status=d["event"]["code"],
                    occurred_at=datetime.fromtimestamp(d["event"]["occurredAtEpochMs"] / 1000, timezone.utc),
                    location=d["hub"])
    if payload_format == "json_es":
        d = json.loads(body)
        return dict(event_id=d["id_evento"], tracking=d["guia"], status=d["estado"],
                    occurred_at=datetime.fromisoformat(d["fecha"]).astimezone(timezone.utc),
                    location=d["ciudad"])
    if payload_format == "xml":
        r = ET.fromstring(body)
        return dict(event_id=r.get("id"), tracking=r.findtext("Tracking"), status=r.findtext("Status"),
                    occurred_at=datetime.strptime(r.findtext("Timestamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc),
                    location=r.findtext("Location"))
    if payload_format == "form":
        q = {k: v[0] for k, v in parse_qs(body.decode("ascii")).items()}
        return dict(event_id=q["evt"], tracking=q["awb"], status=q["state"],
                    occurred_at=datetime.fromtimestamp(int(q["ts"]), timezone.utc), location=q["city"])
    raise KeyError(payload_format)
