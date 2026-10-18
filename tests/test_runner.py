"""Envío push por HTTP, probado con un transporte simulado y con un servidor real."""
import asyncio
import io
import json
import threading
from collections import Counter

import httpx
import pytest

from tests.helpers import decode
from webhook_simulator.catalog import CARRIERS_BY_SLUG
from webhook_simulator.config import Settings
from webhook_simulator.runner import run
from webhook_simulator.sink import SinkServer


def _settings(**kw):
    base = dict(rate=0, max_events=200, seed=3, target_url_template="http://t/webhooks/{carrier}")
    base.update(kw)
    return Settings(**base)


def _capture(status=200):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(status)

    return seen, httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_envia_exactamente_max_events_a_la_url_de_cada_transportadora():
    seen, client = _capture()
    stats = await run(_settings(), client=client)
    assert len(seen) == stats.sent == stats.delivered == 200 and stats.failed == 0
    assert {r.url.path for r in seen} == {f"/webhooks/{s}" for s in CARRIERS_BY_SLUG}
    for r in seen:
        carrier = CARRIERS_BY_SLUG[r.url.path.rsplit("/", 1)[1]]
        decode(carrier.payload_format, r.content)  # se puede interpretar con su propio formato
        assert r.headers["content-type"].startswith(
            {"xml": "application/xml", "form": "application/x-www-form-urlencoded"}.get(carrier.payload_format, "application/json"))


async def test_los_cinco_formatos_y_estados_variados_llegan():
    seen, client = _capture()
    await run(_settings(max_events=1500), client=client)
    ctypes = Counter(r.headers["content-type"].split(";")[0] for r in seen)
    assert set(ctypes) == {"application/json", "application/xml", "application/x-www-form-urlencoded"}
    per = {s: set() for s in CARRIERS_BY_SLUG}
    for r in seen:
        slug = r.url.path.rsplit("/", 1)[1]
        per[slug].add(decode(CARRIERS_BY_SLUG[slug].payload_format, r.content)["status"])
    assert all(len(v) >= 6 for v in per.values())


async def test_inyecta_duplicados_identicos_y_desorden_reales():
    seen, client = _capture()
    stats = await run(_settings(duplicate_rate=0.3, out_of_order_rate=0.3, max_events=600), client=client)
    bodies = Counter(r.content for r in seen)
    assert sum(c - 1 for c in bodies.values()) > 0  # mensajes repetidos idénticos
    assert stats.duplicates > 0 and stats.out_of_order > 0
    # contar desorden desde lo recibido, de forma independiente al resumen
    newest, ooo, ids = {}, 0, set()
    for r in seen:
        slug = r.url.path.rsplit("/", 1)[1]
        d = decode(CARRIERS_BY_SLUG[slug].payload_format, r.content)
        if d["event_id"] in ids:
            continue
        ids.add(d["event_id"])
        if d["tracking"] in newest and newest[d["tracking"]] > d["occurred_at"]:
            ooo += 1
        newest[d["tracking"]] = max(newest.get(d["tracking"], d["occurred_at"]), d["occurred_at"])
    assert ooo > 0


async def test_sin_caos_no_hay_repetidos():
    seen, client = _capture()
    await run(_settings(duplicate_rate=0, out_of_order_rate=0, max_events=300), client=client)
    assert len({r.content for r in seen}) == len(seen)


async def test_respuestas_de_error_se_cuentan_como_fallos():
    _, client = _capture(500)
    stats = await run(_settings(max_events=20), client=client)
    assert stats.sent == 20 and stats.failed == 20 and stats.delivered == 0


async def test_error_de_red_se_cuenta_y_no_detiene_el_simulador():
    def boom(request):
        raise httpx.ConnectError("sin conexión")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    stats = await run(_settings(max_events=15), client=client)
    assert stats.sent == 15 and stats.failed == 15


async def test_dry_run_no_envia_nada_y_imprime_json_por_linea():
    out = io.StringIO()
    stats = await run(_settings(dry_run=True, max_events=30), out=out)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert len(lines) == 30 == stats.sent and stats.delivered == 0
    assert {"carrier", "url", "content_type", "duplicate", "body"} <= set(lines[0])


async def test_misma_semilla_misma_secuencia():
    a, b = io.StringIO(), io.StringIO()
    fixed = lambda: __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)
    await run(_settings(dry_run=True, seed=8), out=a, clock=fixed)
    await run(_settings(dry_run=True, seed=8), out=b, clock=fixed)
    assert a.getvalue() == b.getvalue()


async def test_stop_detiene_el_bucle_sin_limite():
    seen, client = _capture()
    stop = asyncio.Event()
    task = asyncio.create_task(run(_settings(max_events=0, rate=200), client=client, stop=stop))
    await asyncio.sleep(0.2)
    stop.set()
    stats = await asyncio.wait_for(task, 2)
    assert 0 < stats.sent == len(seen)


async def test_integracion_http_real_contra_el_receptor_de_pruebas():
    server = SinkServer(("127.0.0.1", 0))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        settings = _settings(target_url_template=f"http://127.0.0.1:{port}/webhooks/{{carrier}}",
                             duplicate_rate=0.2, max_events=250)
        stats = await run(settings)
        assert stats.delivered == 250 and stats.failed == 0
        async with httpx.AsyncClient() as c:
            got = (await c.get(f"http://127.0.0.1:{port}/stats")).json()
        assert got["total"] == 250
        assert set(got["per_carrier"]) == set(CARRIERS_BY_SLUG)
        assert got["repeated_payloads"] == stats.duplicates > 0
    finally:
        server.shutdown()
        server.server_close()


async def test_resumen_cuenta_solo_lo_enviado_al_detener():
    seen, client = _capture()
    stop = asyncio.Event()
    task = asyncio.create_task(run(_settings(max_events=0, rate=200, shipments_per_batch=50), client=client, stop=stop))
    await asyncio.sleep(0.15)
    stop.set()
    stats = await asyncio.wait_for(task, 2)
    assert stats.sent == len(seen)
    assert stats.unique_events + stats.duplicates == stats.sent


async def test_estadisticas_coinciden_con_lo_recibido():
    seen, client = _capture()
    stats = await run(_settings(duplicate_rate=0.3, out_of_order_rate=0.3, max_events=400), client=client)
    assert stats.unique_events + stats.duplicates == stats.sent == 400
    assert stats.duplicates == len(seen) - len({r.content for r in seen})
