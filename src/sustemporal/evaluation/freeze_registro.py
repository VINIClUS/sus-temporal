"""Registro append-only das avaliações, com resultados nulos e correções declaradas (T11).

Cada linha JSON leva o próprio hash e o hash da linha anterior; reescrever ou apagar qualquer
linha quebra o encadeamento e o registro é recusado. Toda avaliação entra, inclusive a de
resultado nulo (métricas sem valor). Depois da abertura do teste, nova rodada confirmatória do
mesmo congelamento só entra como correção declarada, e a rodada anterior permanece.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sustemporal.contracts.experiment import ModoExecucao
from sustemporal.errors import FalhaOperacionalErro, PortaoRecusado

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sustemporal.contracts import EvaluationReport

__all__ = ["exigir_rodada_permitida", "ler_registro", "registrar_execucao"]

logger = logging.getLogger(__name__)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _canonico(conteudo: dict[str, Any]) -> str:
    return json.dumps(conteudo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ler_registro(registro: Path) -> list[dict[str, Any]]:
    """Entradas do registro, conferindo o encadeamento de cada linha com a anterior.

    Raises:
        FalhaOperacionalErro: linha alterada, removida, reordenada ou ilegível.
    """
    if not registro.exists():
        return []
    entradas: list[dict[str, Any]] = []
    anterior = None
    for numero, linha in enumerate(registro.read_text(encoding="utf-8").splitlines()):
        try:
            entrada = json.loads(linha)
            proprio = entrada.pop("hash")
        except (ValueError, KeyError, AttributeError) as erro:
            raise FalhaOperacionalErro(f"registro_adulterado linha={numero}") from erro
        integra = proprio == _sha(_canonico(entrada))
        if not integra or entrada.get("seq") != numero or entrada.get("anterior") != anterior:
            raise FalhaOperacionalErro(f"registro_adulterado linha={numero}")
        entradas.append(entrada)
        anterior = proprio
    return entradas


def _exigir_correcao_valida(
    entradas: list[dict[str, Any]], corrige: str | None, declaracao: str | None
) -> None:
    if corrige is None:
        return
    if not (declaracao or "").strip():
        raise ValueError(f"correcao_sem_declaracao corrige={corrige}")
    if corrige not in {entrada["report_id"] for entrada in entradas}:
        raise ValueError(f"correcao_de_execucao_inexistente corrige={corrige}")


def _exigir_unica_rodada(
    entradas: list[dict[str, Any]], modo: ModoExecucao, freeze_id: str | None
) -> None:
    if modo is not ModoExecucao.CONFIRMATORIO:
        return
    if any(
        entrada["modo"] == ModoExecucao.CONFIRMATORIO.value and entrada["freeze_id"] == freeze_id
        for entrada in entradas
    ):
        raise PortaoRecusado(f"reabertura_do_teste_sem_correcao_declarada freeze={freeze_id}")


def exigir_rodada_permitida(registro: Path, modo: ModoExecucao, freeze_id: str | None) -> None:
    """Recusa, antes de avaliar, a segunda rodada confirmatória sem correção declarada.

    Raises:
        PortaoRecusado: já existe rodada confirmatória para o congelamento.
        FalhaOperacionalErro: registro adulterado.
    """
    _exigir_unica_rodada(ler_registro(registro), modo, freeze_id)


def registrar_execucao(
    registro: Path,
    relatorio: EvaluationReport,
    *,
    corrige: str | None = None,
    declaracao: str | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Acrescenta uma entrada; nunca reescreve nem apaga as anteriores.

    Raises:
        FalhaOperacionalErro: registro existente adulterado.
        ValueError: correção sem declaração ou de execução inexistente.
        PortaoRecusado: segunda rodada confirmatória do mesmo congelamento sem correção.
    """
    entradas = ler_registro(registro)
    _exigir_correcao_valida(entradas, corrige, declaracao)
    if corrige is None:
        _exigir_unica_rodada(entradas, relatorio.modo, relatorio.freeze_id)
    agora = (relogio or (lambda: datetime.now(UTC)))()
    entrada: dict[str, Any] = {
        "seq": len(entradas),
        "anterior": _sha(_canonico(entradas[-1])) if entradas else None,
        "registrado_em": agora.isoformat(),
        "report_id": relatorio.report_id,
        "modo": relatorio.modo.value,
        "origem_dados": relatorio.origem_dados.value,
        "freeze_id": relatorio.freeze_id,
        "decisao_g2": relatorio.decisao_g2,
        "runs": list(relatorio.runs),
        "metricas": len(relatorio.metricas),
        "metricas_nulas": sum(1 for m in relatorio.metricas if m.valor is None),
        "corrige": corrige,
        "declaracao": declaracao,
    }
    registro.parent.mkdir(parents=True, exist_ok=True)
    with registro.open("a", encoding="utf-8") as arquivo:
        arquivo.write(_canonico(_com_hash(entrada)) + "\n")
    logger.info("execucao_registrada report=%s seq=%d", relatorio.report_id, entrada["seq"])
    return entrada


def _com_hash(entrada: dict[str, Any]) -> dict[str, Any]:
    return {**entrada, "hash": _sha(_canonico(entrada))}
