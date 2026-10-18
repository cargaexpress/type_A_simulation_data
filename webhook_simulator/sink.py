"""Receptor de pruebas: guarda en memoria lo que llega por webhook, para ver el simulador en acción.

Solo usa la biblioteca estándar. NO interpreta los mensajes: los guarda tal cual llegan.
  POST /webhooks/<transportadora>   recibe un evento
  GET  /stats                       totales, por transportadora y mensajes idénticos repetidos
  GET  /received?carrier=&limit=    últimos mensajes recibidos
  GET  /health
"""

import argparse
import hashlib
import json
import logging
import threading
from collections import Counter, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("webhook_simulator.sink")
MAX_STORED = 10_000


class SinkState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.received: deque[dict] = deque(maxlen=MAX_STORED)
        self.per_carrier: Counter = Counter()
        self.payload_hashes: Counter = Counter()

    def add(self, carrier: str, content_type: str, body: bytes) -> None:
        with self.lock:
            self.received.append(
                {
                    "carrier": carrier,
                    "content_type": content_type,
                    "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "body": body.decode("utf-8", errors="replace"),
                }
            )
            self.per_carrier[carrier] += 1
            self.payload_hashes[hashlib.sha256(body).hexdigest()] += 1

    def stats(self) -> dict:
        with self.lock:
            total = sum(self.per_carrier.values())
            distinct = len(self.payload_hashes)
            return {
                "total": total,
                "per_carrier": dict(sorted(self.per_carrier.items())),
                "distinct_payloads": distinct,
                "repeated_payloads": total - distinct,
            }


class _Handler(BaseHTTPRequestHandler):
    server: "SinkServer"

    def _reply(self, status: int, payload: dict | list) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "webhooks" or not parts[1]:
            self._reply(404, {"error": "usa POST /webhooks/<transportadora>"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.server.state.add(parts[1], self.headers.get("Content-Type", ""), body)
        self._reply(200, {"status": "received"})

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/health":
            self._reply(200, {"status": "ok"})
        elif url.path == "/stats":
            self._reply(200, self.server.state.stats())
        elif url.path == "/received":
            carrier = query.get("carrier", [None])[0]
            limit = int(query.get("limit", ["50"])[0])
            with self.server.state.lock:
                items = [m for m in self.server.state.received if carrier in (None, m["carrier"])]
            self._reply(200, items[-limit:] if limit > 0 else [])
        else:
            self._reply(404, {"error": "no existe"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        log.debug("%s - %s", self.address_string(), format % args)


class SinkServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(address, _Handler)
        self.state = SinkState()


def main() -> None:
    parser = argparse.ArgumentParser(prog="webhook_simulator.sink", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = SinkServer((args.host, args.port))
    log.info("receptor de pruebas escuchando en %s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
