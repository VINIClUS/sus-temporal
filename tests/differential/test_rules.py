"""Diferencial SINTETICO: motor SQL × avaliador de referência independente (model.md)."""

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from sustemporal.contracts.rules import RuleSpec
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.reference import agregar_referencia, avaliar_referencia
from tests.fixtures.regras_bateria import BATERIA
from tests.fixtures.regras_cenario import CenarioRegras, para_referencia
from tests.fixtures.regras_estrategias import cenarios, regras_variadas
from tests.fixtures.regras_execucao import executar, tabela

_CAMPOS = ("estado", "aplicabilidade", "insumos_completos", "incompatibilidade_demonstrada")


def _motor(cenario: CenarioRegras, regras: list[RuleSpec]) -> tuple[dict, dict, int]:
    with tempfile.TemporaryDirectory() as diretorio:
        resultado = executar(Path(diretorio), cenario, regras=regras)
        avaliacoes = {
            (a["row_id"], a["rule_id"]): (*(a[c] for c in _CAMPOS), a["motivos"])
            for a in tabela(resultado, "avaliacoes.v1")
        }
        agregados = {
            a["row_id"]: a["resultado"] for a in tabela(resultado, "agregados_registro.v1")
        }
        return avaliacoes, agregados, resultado.falhas


def _referencia(cenario: CenarioRegras, regras: list[RuleSpec]) -> tuple[dict, dict]:
    lista = avaliar_referencia(para_referencia(cenario), regras)
    avaliacoes = {
        (a.row_id, a.rule_id): (
            a.estado.value,
            a.aplicabilidade.value,
            a.insumos_completos,
            a.incompatibilidade_demonstrada,
            ";".join(m.value for m in a.motivos),
        )
        for a in lista
    }
    agregados = {row_id: r.value for row_id, r in agregar_referencia(lista).items()}
    return avaliacoes, agregados


@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
@given(cenario=cenarios(), regras=regras_variadas())
def test_motor_sql_equivale_ao_avaliador_de_referencia(
    cenario: CenarioRegras, regras: list[RuleSpec]
) -> None:
    avaliacoes, agregados, falhas = _motor(cenario, regras)
    esperadas, agregados_esperados = _referencia(cenario, regras)
    assert falhas == 0
    assert avaliacoes == esperadas
    assert agregados == agregados_esperados


@pytest.mark.parametrize("nome", sorted(BATERIA))
def test_motor_sql_equivale_a_referencia_nos_exemplos_manuais(nome: str) -> None:
    cenario = BATERIA[nome]
    regras = carregar_regras()
    avaliacoes, agregados, falhas = _motor(cenario, regras)
    esperadas, agregados_esperados = _referencia(cenario, regras)
    assert falhas == 0
    assert avaliacoes == esperadas
    assert agregados == agregados_esperados
