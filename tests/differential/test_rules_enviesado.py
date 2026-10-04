"""Diferencial SINTETICO enviesado (revisão I4): motor × referência com VIOLACAO e CONFORME."""

from hypothesis import HealthCheck, given, settings

from sustemporal.rules.catalog import carregar_regras
from tests.differential.test_rules import _motor, _referencia
from tests.fixtures.regras_cenario import CenarioRegras
from tests.fixtures.regras_estrategias_enviesadas import cenarios_enviesados


@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
@given(cenario=cenarios_enviesados())
def test_motor_sql_equivale_a_referencia_em_cenarios_enviesados(cenario: CenarioRegras) -> None:
    regras = carregar_regras()
    avaliacoes, agregados, falhas = _motor(cenario, regras)
    esperadas, agregados_esperados = _referencia(cenario, regras)
    assert falhas == 0
    assert avaliacoes == esperadas
    assert agregados == agregados_esperados
