"""Varredura do que a cadeia do `reproduce` lê: nenhum campo fica sem tratamento (T14).

Todo campo do `FreezeManifest` e da config (com os de `runtime` e `piloto`) tem a fonte da
verdade, a conferência e o efeito de a reprodução o ler de outro lugar. Campo novo num contrato
falha aqui até alguém decidir o tratamento, e o campo lido que o congelamento ou o registro fixam
não pode ficar sem conferência sem dizer o efeito. As tabelas da seção 5.5 do runbook de
reprodução saem destes dados, linha a linha.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sustemporal.contracts.config import PilotSpec, RunConfig, RuntimeConfig
from sustemporal.contracts.experiment import FreezeManifest
from sustemporal.reporting.reproduce_varredura import (
    CAMPOS_DA_CONFIG,
    CAMPOS_DO_CONGELAMENTO,
    Conferencia,
    Fonte,
    Tratamento,
)

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "reproducao.md"


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


@pytest.mark.parametrize("tratamentos", [CAMPOS_DO_CONGELAMENTO, CAMPOS_DA_CONFIG])
def test_todo_tratamento_diz_o_efeito(tratamentos: dict[str, Tratamento]) -> None:
    assert all(t.efeito.strip() for t in tratamentos.values())


@pytest.mark.parametrize("tratamentos", [CAMPOS_DO_CONGELAMENTO, CAMPOS_DA_CONFIG])
def test_campo_sem_fonte_nao_tem_conferencia_de_item_nem_de_observacao(
    tratamentos: dict[str, Tratamento],
) -> None:
    for campo, tratamento in tratamentos.items():
        if tratamento.fonte is Fonte.NENHUMA:
            assert tratamento.conferencia in {Conferencia.NENHUMA, Conferencia.RECUSA}, campo


@pytest.mark.parametrize("tratamentos", [CAMPOS_DO_CONGELAMENTO, CAMPOS_DA_CONFIG])
def test_o_runbook_traz_a_linha_de_cada_campo_da_varredura(
    tratamentos: dict[str, Tratamento],
) -> None:
    linhas = set(RUNBOOK.read_text(encoding="utf-8").splitlines())
    faltando = [c for c, t in tratamentos.items() if _linha_do_runbook(c, t) not in linhas]
    assert faltando == []
