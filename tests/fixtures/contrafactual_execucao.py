"""Execução SINTETICA pela CLI `validate` com três linhas de referência para o contrafactual.

- ausência: par CNES–CBO fora do CNES PF da competência selecionada (VIOLACAO);
- mês faltante: competência de atendimento sem versão do CNES PF (seleção AUSENTE);
- borda de 2018: atendimento em 201712 e processamento em 201801, com política de atendimento;
  existe versão do CNES PF de 201801 que resolveria o par se fosse usada (mês vizinho).

O `validate` grava `entrada_validacao.json` ao lado do `run_result.json`; a fixture nunca escreve
na pasta da execução, então o contrafactual lê o arquivo que o próprio `validate` gravou.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.config import RunConfig, RuntimeConfig
from sustemporal.execucoes import raiz_execucoes
from sustemporal.rules.cli import EntradaValidacao, executar_validate
from tests.fixtures.contrafactual_cenario import (
    ART_ST,
    CBO_ALVO,
    CBO_OUTRO,
    CNES,
    OpcoesST,
    gravar_st,
)
from tests.fixtures.regras_cenario import artefato, materializar, snapshot_vazio
from tests.fixtures.regras_exemplos import ART_CNES, ART_SIA, COMPETENCIA, cenario_base, registro

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ARQUIVO_ENTRADA", "Execucao", "entrada_sintetica", "executar_validacao_sintetica"]

ARQUIVO_ENTRADA = "entrada_validacao.json"
_PF = "cnes_estab_cbo.v1"
_ART_PF_2018 = artefato(6)


@dataclass(frozen=True)
class Execucao:
    config: RunConfig
    raiz: Path
    run_id: str
    ausencia: str
    mes_faltante: str
    borda_2018: str


def _registros() -> tuple[dict[str, str | None], ...]:
    return (
        registro(0, cbo=CBO_ALVO),
        registro(
            1, cbo=CBO_ALVO, competencia_atendimento="202002", competencia_processamento="202002"
        ),
        registro(
            2, cbo=CBO_ALVO, competencia_atendimento="201712", competencia_processamento="201801"
        ),
    )


def _ausentes(selecoes: tuple[dict[str, str | None], ...]) -> tuple[dict[str, str | None], ...]:
    """Linhas 1 e 2 sem versão na competência requerida: seleção AUSENTE, sem artefato."""
    ausentes = {f"{ART_SIA}#1", f"{ART_SIA}#2"}
    return tuple(
        s | {"estado": "AUSENTE", "artifact_ids": ""} if s["row_id"] in ausentes else s
        for s in selecoes
    )


def _pf() -> tuple[dict[str, object], ...]:
    base = {"cnes": CNES, "n_vinculos": 2}
    return (
        base | {"artifact_id": ART_CNES, "competencia_arquivo": COMPETENCIA, "cbo": CBO_OUTRO},
        base | {"artifact_id": _ART_PF_2018, "competencia_arquivo": "201801", "cbo": CBO_ALVO},
    )


def entrada_sintetica(raiz: Path) -> EntradaValidacao:
    cenario = cenario_base(*_registros())
    integridade = dict(cenario.integridade) | dict.fromkeys(
        (ART_ST, _ART_PF_2018), EstadoIntegridade.OK
    )
    cenario = cenario.com(
        selecoes=_ausentes(cenario.selecoes),
        auxiliares=dict(cenario.auxiliares) | {_PF: _pf()},
        integridade=integridade,
    )
    dataset, insumos = materializar(cenario, raiz / "entrada")
    st = gravar_st(raiz / "entrada", OpcoesST())
    return EntradaValidacao(
        dataset=dataset,
        snapshots=snapshot_vazio(),
        auxiliares=(*insumos.auxiliares, st),
        selecoes=insumos.selecoes,
        cobertura=insumos.cobertura,
        integridade=dict(insumos.integridade),
    )


def executar_validacao_sintetica(raiz: Path) -> Execucao:
    """`executar_validate` (`--policy atendimento`) sem `--saida`: a execução fica em `runs/`.

    A entrada é a que o `validate` grava ao lado do `run_result.json`.
    """
    entrada = entrada_sintetica(raiz)
    caminho = raiz / "entrada.json"
    caminho.write_text(entrada.model_dump_json(), encoding="utf-8")
    config = RunConfig(versao="1", runtime=RuntimeConfig(raiz_saidas=str(raiz / "saidas")))
    args = argparse.Namespace(policy="atendimento", entrada=caminho, ingest=None, saida=None)
    assert executar_validate(args, config) == 0
    (pasta,) = list(raiz_execucoes(config).iterdir())
    return Execucao(
        config=config,
        raiz=raiz,
        run_id=pasta.name,
        ausencia=f"{ART_SIA}#0",
        mes_faltante=f"{ART_SIA}#1",
        borda_2018=f"{ART_SIA}#2",
    )
