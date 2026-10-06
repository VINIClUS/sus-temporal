"""Rodada registrada do congelamento como o registro a descreve (T14).

O registro de rodadas (`registro_execucoes.jsonl`, encadeado) diz qual relatório, de que modo e
com que execuções cada avaliação foi registrada. O `reproduce` só compara com o relatório que bate
com a entrada do registro: um relatório válido que não é o registrado (arquivo copiado ou trocado)
vale como original indisponível (inconclusão), nunca como original.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sustemporal.evaluation.cli import REGISTRO
from sustemporal.evaluation.freeze_registro import ler_registro
from sustemporal.execucoes import ExecucaoNaoResolvida, ler_execucao, raiz_execucoes
from sustemporal.reporting.reproduce_comparacao import ler_relatorio_original, rodada_registrada

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.evaluation import EvaluationReport
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.temporal import MetodoId

__all__ = ["Original", "campos_que_nao_conferem", "ler_original"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Original:
    """Rodada registrada do congelamento: o relatório e as execuções, se ainda existem.

    `observacoes` diz por que um relatório lido foi recusado.
    """

    relatorio: EvaluationReport | None
    execucoes: Mapping[MetodoId, RunResult]
    observacoes: tuple[str, ...] = ()


def campos_que_nao_conferem(relatorio: EvaluationReport, entrada: Mapping[str, Any]) -> list[str]:
    """Campos em que o relatório difere da entrada do registro, na ordem do registro.

    O registro guarda `report_id`, `freeze_id`, o modo, a origem dos dados, a lista de execuções e
    a contagem das métricas (e das nulas); campo que a entrada não traz não confere.
    """
    nulas = sum(1 for metrica in relatorio.metricas if metrica.valor is None)
    lidos = {
        "report_id": relatorio.report_id,
        "freeze_id": relatorio.freeze_id,
        "modo": relatorio.modo.value,
        "origem_dados": relatorio.origem_dados.value,
        "runs": list(relatorio.runs),
        "metricas": len(relatorio.metricas),
        "metricas_nulas": nulas,
    }
    return [campo for campo, lido in lidos.items() if entrada.get(campo) != lido]


def _relatorio_registrado(
    config: RunConfig, freeze_id: str, entrada: Mapping[str, Any]
) -> tuple[EvaluationReport | None, tuple[str, ...]]:
    caminho = (
        Path(config.runtime.raiz_saidas) / "avaliacao" / freeze_id / f"{entrada['report_id']}.json"
    )
    relatorio = ler_relatorio_original(caminho)
    if relatorio is None:
        return None, ()
    campos = campos_que_nao_conferem(relatorio, entrada)
    if not campos:
        return relatorio, ()
    lista = ",".join(campos)
    logger.warning(
        "relatorio_original_nao_confere report=%s campos=%s", entrada["report_id"], lista
    )
    return None, (f"relatorio_original_nao_confere_com_o_registro campos={lista}",)


def _execucoes(config: RunConfig, entrada: Mapping[str, Any]) -> dict[MetodoId, RunResult]:
    execucoes = {}
    for run_id in entrada["runs"]:
        try:
            run = ler_execucao(raiz_execucoes(config), run_id)
        except ExecucaoNaoResolvida:
            continue
        if run.metodo is not None:
            execucoes[run.metodo] = run
    return execucoes


def ler_original(config: RunConfig, freeze_id: str) -> Original:
    """A última rodada registrada do congelamento e do modo: relatório conferido e execuções.

    Sem registro, sem rodada do congelamento e do modo, ou com o relatório ausente, ilegível ou que
    não bate com a entrada do registro, não há relatório; a execução ausente fica de fora.

    Raises:
        FalhaOperacionalErro: registro de rodadas adulterado.
    """
    registro = ler_registro(Path(config.runtime.dir_congelamentos) / REGISTRO)
    entrada = rodada_registrada(registro, freeze_id, config.modo.value)
    if entrada is None:
        return Original(None, {})
    relatorio, observacoes = _relatorio_registrado(config, freeze_id, entrada)
    return Original(relatorio, _execucoes(config, entrada), observacoes)
