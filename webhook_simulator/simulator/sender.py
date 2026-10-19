"""Senders: the "how do we get a message out the door" part, behind one tiny interface.

The runner doesn't care whether it's talking to a real HTTP server or just printing
(dry-run), so both live here and share the same `send()` shape.
"""

import json
from dataclasses import dataclass
from typing import Protocol, TextIO

import httpx

from webhook_simulator import __version__
from webhook_simulator.domain.catalog import CARRIERS_BY_SLUG
from webhook_simulator.domain.chaos import Delivery
from webhook_simulator.formats import EncodedRequest, encode

USER_AGENT = f"carrier-webhook-simulator/{__version__}"


@dataclass(frozen=True, slots=True)
class SendResult:
    delivered: bool
    error: str | None = None  # human-readable reason when `delivered` is False


class Sender(Protocol):
    async def send(self, delivery: Delivery) -> SendResult: ...


def _encode(delivery: Delivery) -> EncodedRequest:
    event = delivery.event
    return encode(CARRIERS_BY_SLUG[event.carrier].payload_format, event)


class HttpSender:
    """Pushes each delivery with an HTTP POST, just like a real carrier would."""

    def __init__(self, client: httpx.AsyncClient, url_template: str) -> None:
        self._client = client
        self._url_template = url_template

    async def send(self, delivery: Delivery) -> SendResult:
        request = _encode(delivery)
        url = self._url_template.format(carrier=delivery.event.carrier)
        try:
            response = await self._client.post(
                url,
                content=request.body,
                headers={"Content-Type": request.content_type, "User-Agent": USER_AGENT},
            )
        except httpx.HTTPError as exc:
            return SendResult(False, f"could not reach {url} ({type(exc).__name__})")
        if response.is_success:
            return SendResult(True)
        return SendResult(False, f"{url} answered {response.status_code}")


class DryRunSender:
    """Prints one JSON line per message instead of sending it."""

    def __init__(self, out: TextIO, url_template: str) -> None:
        self._out = out
        self._url_template = url_template

    async def send(self, delivery: Delivery) -> SendResult:
        request = _encode(delivery)
        line = {
            "carrier": delivery.event.carrier,
            "url": self._url_template.format(carrier=delivery.event.carrier),
            "content_type": request.content_type,
            "duplicate": delivery.duplicate,
            "body": request.body.decode("utf-8"),
        }
        self._out.write(json.dumps(line, ensure_ascii=False) + "\n")
        return SendResult(True)
