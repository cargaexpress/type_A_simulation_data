import pytest
from pydantic import ValidationError

from webhook_simulator.simulator.config import SimulatorSettings, load_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # A developer's shell might have SIM_* variables around; tests must not depend on them.
    import os

    for name in [n for n in os.environ if n.startswith("SIM_")]:
        monkeypatch.delenv(name)


def test_defaults():
    settings = load_settings([])
    assert settings.rate == 5 and settings.max_events == 0 and settings.seed is None
    assert settings.carrier_slugs == ("alpha", "beta", "gamma", "delta", "epsilon")
    assert settings.dry_run is False


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("SIM_RATE", "9")
    monkeypatch.setenv("SIM_DRY_RUN", "true")
    monkeypatch.setenv("SIM_CARRIERS", "alpha,delta")
    settings = load_settings([])
    assert settings.rate == 9 and settings.dry_run is True
    assert settings.carrier_slugs == ("alpha", "delta")


def test_cli_flags_beat_env_vars(monkeypatch):
    monkeypatch.setenv("SIM_RATE", "9")
    monkeypatch.setenv("SIM_DRY_RUN", "true")
    settings = load_settings(["--rate", "2", "--no-dry-run", "--seed", "42"])
    assert settings.rate == 2 and settings.dry_run is False and settings.seed == 42


def test_empty_env_var_counts_as_unset(monkeypatch):
    monkeypatch.setenv("SIM_SEED", "")  # docker compose passes `SIM_SEED=` when you don't set it
    assert load_settings([]).seed is None


def test_carriers_are_normalized():
    assert load_settings(["--carriers", " Alpha , BETA "]).carrier_slugs == ("alpha", "beta")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_url_template": "http://x/webhooks"},  # no {carrier}
        {"carriers": "alpha,zeta"},
        {"carriers": " , "},
        {"rate": -1},
        {"shipments_per_batch": 0},
        {"max_events": -1},
        {"duplicate_rate": 1.5},
        {"out_of_order_rate": -0.1},
        {"duplicate_max_delay": -1},
        {"request_timeout": 0},
    ],
)
def test_invalid_values_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        SimulatorSettings(**kwargs)


def test_settings_are_immutable():
    with pytest.raises(ValidationError):
        load_settings([]).rate = 1
