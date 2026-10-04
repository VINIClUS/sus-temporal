"""Insumos da execução avaliada que a busca de contrafactuais revalida (T09)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.temporal import MetodoId
from sustemporal.explanation.cli import ExecucaoNaoResolvida, localizar_execucao
from sustemporal.rules.catalog import CatalogoInvalido, carregar_regras
from sustemporal.rules.cli import EntradaValidacao
from sustemporal.rules.engine import calcular_run_id
from sustemporal.rules.insumos import InsumosAvaliacao, MetodoInvalido, politica_padrao

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sustemporal.contracts import (
        DatasetRef,
        PoliticaTemporal,
        RuleSpec,
        RunConfig,
        RunResult,
        SnapshotSet,
    )

__all__ = [
    "ARQUIVO_ENTRADA",
    "ContextoContrafactual",
    "ContextoIndisponivel",
    "contexto_da_execucao",
]

logger = logging.getLogger(__name__)

ARQUIVO_ENTRADA = "entrada_validacao.json"
_DIRETORIOS_DE_EXECUCAO = ("runs", "validacao")
_ST = "cnes_estabelecimento.v1"


def _agora() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ContextoContrafactual:
    """Conjunto SIA-PA, seleção, regras e insumos com que o motor avaliou o registro.

    `cadastros`: conjuntos `cnes_*` lidos só pelas precondições (CNES ST, por exemplo), além dos
    auxiliares das regras. `competencia_aberta_cnes`: competência que evidência atual mostra aberta
    no CNES; `None` quando só há fontes históricas. Os arquivos nunca são alterados: a busca
    trabalha numa cópia em diretório temporário.
    """

    dataset: DatasetRef
    snapshots: SnapshotSet
    regras: tuple[RuleSpec, ...]
    insumos: InsumosAvaliacao
    cadastros: tuple[DatasetRef, ...] = ()
    competencia_aberta_cnes: str | None = None
    relogio: Callable[[], datetime] = _agora


class ContextoIndisponivel(ValueError):
    """Insumos da execução ausentes, ilegíveis ou divergentes do `run_id`."""


def _entrada(raiz: Path, run_id: str) -> EntradaValidacao:
    """`entrada_validacao.json` ao lado do `run_result.json` exato; nunca uma pasta "latest"."""
    caminhos = [raiz / nome / run_id / ARQUIVO_ENTRADA for nome in _DIRETORIOS_DE_EXECUCAO]
    existentes = [c for c in caminhos if c.is_file()]
    if not existentes:
        raise ContextoIndisponivel(f"contexto_da_execucao_ausente run={run_id}")
    if len(existentes) > 1:
        raise ContextoIndisponivel(
            f"contexto_da_execucao_ambiguo run={run_id} entradas={len(existentes)}"
        )
    try:
        return EntradaValidacao.model_validate_json(existentes[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as erro:
        raise ContextoIndisponivel(
            f"contrafactual_sem_contexto run={run_id} entrada_ilegivel={existentes[0]}"
        ) from erro


def _politica(
    run: RunResult, entrada: EntradaValidacao, regras: list[RuleSpec]
) -> PoliticaTemporal:
    """A mesma política que `validate` usa para o método gravado na execução."""
    if run.metodo is None:
        raise ContextoIndisponivel(f"contrafactual_sem_contexto run={run.run_id} metodo=ausente")
    documentada = entrada.politica_documentada
    if run.metodo is MetodoId.M_TEMP and documentada is not None:
        return documentada
    try:
        return politica_padrao(run.metodo, regras)
    except MetodoInvalido as erro:
        raise ContextoIndisponivel(f"contrafactual_sem_contexto run={run.run_id}") from erro


def contexto_da_execucao(raiz: Path, run_id: str, config: RunConfig) -> ContextoContrafactual:
    """Insumos gravados na pasta exata da execução, conferidos pelo `run_id` recalculado.

    O `run_id` deriva de conjunto, seleção, regras, política, configuração (sem `runtime`),
    auxiliares e integridade; recalculá-lo prova que os insumos são os da execução.

    Raises:
        ContextoIndisponivel: execução, entrada ou catálogo ausentes, ou `run_id` divergente.
    """
    try:
        run = localizar_execucao(raiz, run_id)
        regras = carregar_regras()
    except (ExecucaoNaoResolvida, CatalogoInvalido) as erro:
        raise ContextoIndisponivel(f"contrafactual_sem_contexto run={run_id} erro={erro}") from erro
    entrada = _entrada(raiz, run_id)
    insumos = InsumosAvaliacao(
        auxiliares=entrada.auxiliares,
        selecoes=entrada.selecoes,
        cobertura=entrada.cobertura,
        integridade=entrada.integridade,
        politica=_politica(run, entrada, regras),
    )
    recalculado = calcular_run_id(entrada.dataset, entrada.snapshots, regras, config, insumos)
    if recalculado != run_id:
        raise ContextoIndisponivel(
            f"contrafactual_contexto_diverge_da_execucao run={run_id} recalculado={recalculado}"
        )
    logger.info("contrafactual_contexto_resolvido run=%s", run_id)
    return ContextoContrafactual(
        dataset=entrada.dataset,
        snapshots=entrada.snapshots,
        regras=tuple(regras),
        insumos=insumos,
        cadastros=tuple(d for d in entrada.auxiliares if d.schema_id == _ST),
    )
