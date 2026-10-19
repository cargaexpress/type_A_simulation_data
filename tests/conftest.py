import random
from datetime import UTC, datetime

import pytest

from webhook_simulator.domain.catalog import CARRIERS
from webhook_simulator.domain.generator import EventGenerator
from webhook_simulator.receiver.api import create_app
from webhook_simulator.receiver.config import ReceiverSettings
from webhook_simulator.receiver.repository import EventRepository

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def make_generator():
    def _make(seed=1):
        return EventGenerator(CARRIERS, random.Random(seed), clock=lambda: NOW)

    return _make


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "events.db"


@pytest.fixture
def receiver_settings(db_path):
    return ReceiverSettings(db_path=str(db_path))


@pytest.fixture
def app(receiver_settings):
    return create_app(receiver_settings, clock=lambda: NOW)


@pytest.fixture
def repository(app, db_path):
    # `app` is requested so the schema exists before the repository is used.
    return EventRepository(db_path)
