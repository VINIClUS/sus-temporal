"""Varredura do que a cadeia do `reproduce` lê e compara: nenhum campo fica sem tratamento (T14).

Todo campo do `FreezeManifest` e da config (com os de `runtime` e `piloto`), e os de `DatasetRef`,
`SplitManifest` e `EvaluationReport` que as comparações projetam ou deixam de fora, tem a fonte da
verdade, a conferência e o efeito. Campo novo num contrato falha aqui até alguém decidir o
tratamento, e o campo lido que o congelamento ou o registro fixam não pode ficar sem conferência
sem dizer o efeito. Cada comparação diz o que confere antes de projetar e o que deixa de fora. As
tabelas das seções 5.5 e 5.6 do runbook de reprodução saem destes dados, linha a linha.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts.config import PilotSpec, RunConfig, RuntimeConfig
from sustemporal.contracts.evaluation import EvaluationReport
from sustemporal.contracts.experiment import FreezeManifest, SplitManifest
from sustemporal.contracts.records import DatasetRef
from sustemporal.reporting.reproduce_varredura import (
    CAMPOS_DA_CONFIG,
    CAMPOS_DA_REFERENCIA,
    CAMPOS_DO_CONGELAMENTO,
    CAMPOS_DO_RELATORIO,
    CAMPOS_DO_SPLIT,
    COMPARACOES,
    Conferencia,
    Fonte,
    Tratamento,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "reproducao.md"
TABELAS = [
    CAMPOS_DO_CONGELAMENTO,
    CAMPOS_DA_CONFIG,
    CAMPOS_DA_REFERENCIA,
    CAMPOS_DO_SPLIT,
    CAMPOS_DO_RELATORIO,
]


def _linha_do_runbook(campo: str, tratamento: Tratamento) -> str:
    fonte, conferencia = tratamento.fonte.value, tratamento.conferencia.value
    return f"| `{campo}` | {fonte} | {conferencia} | {tratamento.efeito} |"


def _campos_da_config() -> set[str]:
    topo = set(RunConfig.model_fields) - {"runtime", "piloto"}
    runtime = {f"runtime.{campo}" for campo in RuntimeConfig.model_fields}
    piloto = {f"piloto.{campo}" for campo in PilotSpec.model_fields}
    return topo | runtime | piloto


def test_todo_campo_do_manifesto_de_congelamento_tem_tratamento() -> None:
    assert set(CAMPOS_DO_CONGELAMENTO) == set(FreezeManifest.model_fields)


def test_todo_campo_da_config_tem_tratamento_e_nenhum_tratamento_e_de_campo_inexistente() -> None:
    assert set(CAMPOS_DA_CONFIG) == _campos_da_config()


@pytest.mark.parametrize(
    ("tratamentos", "contrato"),
    [
        (CAMPOS_DA_REFERENCIA, DatasetRef),
        (CAMPOS_DO_SPLIT, SplitManifest),
        (CAMPOS_DO_RELATORIO, EvaluationReport),
    ],
)
def test_todo_campo_que_as_comparacoes_projetam_tem_tratamento(
    tratamentos: dict[str, Tratamento], contrato: type[BaseModel]
) -> None:
    assert set(tratamentos) == set(contrato.model_fields)


@pytest.mark.parametrize("tratamentos", TABELAS)
def test_todo_tratamento_diz_o_efeito(tratamentos: dict[str, Tratamento]) -> None:
    assert all(t.efeito.strip() for t in tratamentos.values())


@pytest.mark.parametrize("tratamentos", TABELAS)
def test_campo_sem_fonte_nao_tem_conferencia_de_item_nem_de_observacao(
    tratamentos: dict[str, Tratamento],
) -> None:
    for campo, tratamento in tratamentos.items():
        if tratamento.fonte is Fonte.NENHUMA:
            assert tratamento.conferencia in {Conferencia.NENHUMA, Conferencia.RECUSA}, campo


@pytest.mark.parametrize("tratamentos", TABELAS)
def test_o_runbook_traz_a_linha_de_cada_campo_da_varredura(
    tratamentos: dict[str, Tratamento],
) -> None:
    linhas = set(RUNBOOK.read_text(encoding="utf-8").splitlines())
    faltando = [c for c, t in tratamentos.items() if _linha_do_runbook(c, t) not in linhas]
    assert faltando == []


def test_toda_familia_de_item_comparado_tem_a_sua_linha() -> None:
    assert set(COMPARACOES) == {
        "conjunto:*",
        "split:split_id",
        "split:campos",
        "split:particao:*",
        "split:rotulos:*",
        "saida:*",
        "insumos:*",
        "metricas",
        "notas",
        "relatorio:campos",
    }


def test_toda_comparacao_diz_o_que_confere_antes_e_o_que_deixa_de_fora() -> None:
    assert all(c.antes.strip() and c.fora.strip() for c in COMPARACOES.values())


def test_o_runbook_traz_a_linha_de_cada_comparacao() -> None:
    linhas = set(RUNBOOK.read_text(encoding="utf-8").splitlines())
    esperadas = {item: f"| `{item}` | {c.antes} | {c.fora} |" for item, c in COMPARACOES.items()}
    assert [item for item, linha in esperadas.items() if linha not in linhas] == []
