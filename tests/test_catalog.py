"""RIWI-84: catálogo de al menos 6 estados propios por transportadora."""
import re
from pathlib import Path

import pytest

from webhook_simulator.catalog import CANONICAL_STATUSES, CARRIERS, CARRIERS_BY_SLUG


def test_hay_cinco_transportadoras_con_formatos_distintos():
    assert len(CARRIERS) == 5
    assert len({c.slug for c in CARRIERS}) == 5
    assert len({c.payload_format for c in CARRIERS}) == 5
    assert len({c.tracking_prefix for c in CARRIERS}) == 5


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
def test_al_menos_seis_estados_propios_distintos(carrier):
    raws = [s.raw for s in carrier.statuses]
    assert len(raws) >= 6
    assert len(set(raws)) == len(raws)


@pytest.mark.parametrize("carrier", CARRIERS, ids=lambda c: c.slug)
def test_estados_traducen_a_canonicos_validos_y_cubren_el_ciclo(carrier):
    canon = {s.canonical for s in carrier.statuses}
    assert canon <= set(CANONICAL_STATUSES)
    assert canon == set(CANONICAL_STATUSES)  # los 8 canónicos son expresables
    assert any(s.cancel for s in carrier.statuses)


def test_vocabularios_son_distintos_entre_transportadoras():
    vocabularies = [frozenset(s.raw for s in c.statuses) for c in CARRIERS]
    assert len(set(vocabularies)) == 5


def test_statuses_for():
    alpha = CARRIERS_BY_SLUG["alpha"]
    assert all(s.canonical == "EXCEPTION" for s in alpha.statuses_for("EXCEPTION"))
    assert all(s.cancel for s in alpha.statuses_for("EXCEPTION", cancel=True))
    assert not any(s.cancel for s in alpha.statuses_for("EXCEPTION"))


SEED = Path(__file__).resolve().parents[2] / "backend/alembic/versions/c4a1209b7e6f_hu12_canonical_state_mapping.py"


@pytest.mark.skipif(not SEED.exists(), reason="se ejecuta solo dentro del repositorio completo")
@pytest.mark.parametrize("slug", ["alpha", "beta", "gamma"])
def test_estados_coinciden_con_el_seed_del_backend(slug):
    text = SEED.read_text(encoding="utf-8")
    for status in CARRIERS_BY_SLUG[slug].statuses:
        assert re.search(rf"""["']{re.escape(status.raw)}["']""", text), status.raw
