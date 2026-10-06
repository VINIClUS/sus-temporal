"""Rodada registrada do congelamento como o registro a descreve (T14).

O registro de rodadas (`registro_execucoes.jsonl`, encadeado) diz qual relatório, de que modo e
com que execuções cada avaliação foi registrada. O `reproduce` só compara com o relatório que bate
com a entrada do registro: um relatório válido que não é o registrado (arquivo copiado ou trocado)
vale como original indisponível (inconclusão), nunca como original.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.evaluation import EvaluationReport
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.temporal import MetodoId

__all__ = ["Original", "campos_que_nao_conferem", "ler_original"]


@dataclass(frozen=True)
class Original:
    """Rodada registrada do congelamento: o relatório e as execuções, se ainda existem.

    `observacoes` diz por que um relatório lido foi recusado.
    """

    relatorio: EvaluationReport | None
    execucoes: Mapping[MetodoId, RunResult]
    observacoes: tuple[str, ...] = ()


def campos_que_nao_conferem(relatorio: EvaluationReport, entrada: Mapping[str, Any]) -> list[str]:
    raise NotImplementedError


def ler_original(config: RunConfig, freeze_id: str) -> Original:
    raise NotImplementedError
