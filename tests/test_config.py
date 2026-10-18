import pytest

from webhook_simulator.config import DEFAULT_TARGET, Settings, parse_settings


def test_valores_por_defecto():
    s = parse_settings([], {})
    assert s.target_url_template == DEFAULT_TARGET
    assert s.carriers == ("alpha", "beta", "gamma", "delta", "epsilon")
    assert s.duplicate_rate == 0.10 and s.out_of_order_rate == 0.10
    assert s.seed is None and not s.dry_run


def test_variables_de_entorno():
    env = {"SIM_TARGET_URL_TEMPLATE": "http://x/{carrier}", "SIM_CARRIERS": "alpha, delta",
           "SIM_RATE": "0", "SIM_DUPLICATE_RATE": "0.5", "SIM_OUT_OF_ORDER_RATE": "0.25",
           "SIM_DUPLICATE_MAX_DELAY": "9", "SIM_SEED": "42", "SIM_DRY_RUN": "true",
           "SIM_MAX_EVENTS": "100", "SIM_SHIPMENTS_PER_BATCH": "7", "SIM_REQUEST_TIMEOUT": "2"}
    s = parse_settings([], env)
    assert s == Settings(target_url_template="http://x/{carrier}", carriers=("alpha", "delta"), rate=0,
                         shipments_per_batch=7, max_events=100, duplicate_rate=0.5, out_of_order_rate=0.25,
                         duplicate_max_delay=9, seed=42, dry_run=True, timeout=2)


def test_la_linea_de_comandos_reemplaza_al_entorno():
    s = parse_settings(["--duplicate-rate", "0.9", "--no-dry-run", "--carriers", "beta"],
                       {"SIM_DUPLICATE_RATE": "0.1", "SIM_DRY_RUN": "1"})
    assert s.duplicate_rate == 0.9 and not s.dry_run and s.carriers == ("beta",)


@pytest.mark.parametrize("argv", [
    ["--carriers", "zeta"], ["--duplicate-rate", "3"], ["--rate", "-1"],
    ["--shipments-per-batch", "0"], ["--target-url-template", "http://x/fijo"], ["--max-events", "-1"],
])
def test_valores_invalidos_terminan_con_error(argv):
    with pytest.raises(SystemExit):
        parse_settings(argv, {})
