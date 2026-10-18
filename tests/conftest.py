import random
from datetime import datetime, timezone

import pytest

from webhook_simulator.catalog import CARRIERS
from webhook_simulator.generator import EventGenerator

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def make_generator():
    def _make(seed=1):
        return EventGenerator(CARRIERS, random.Random(seed), clock=lambda: NOW)

    return _make
