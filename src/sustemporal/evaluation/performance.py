"""Harness de desempenho (T13): tempo, memória e armazenamento com ambiente, cache e repetições.

Mede só etapas executáveis. Etapa sem implementação no main (contrafactuais do T09, métricas do
T11) ou stub que levanta `NotImplementedError` sai `NAO_MEDIDO` com motivo, nunca com número
inventado. A escala DRS XI/SP roda na máquina do pesquisador (marcador `perf`, fora do CI).
"""

from __future__ import annotations

import json
import logging
import resource
import time
import tracemalloc
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts import Ambiente, OrigemDados

__all__ = [
    "ETAPAS_PENDENTES",
    "Cache",
    "EstadoMedicao",
    "Etapa",
    "Medicao",
    "etapa_pendente",
    "gravar_relatorio",
    "medir",
]

logger = logging.getLogger(__name__)

ETAPAS_PENDENTES = {
    "contrafactuais": "T09_search_counterfactuals_fora_do_main",
    "metricas": "T11_evaluate_runs_fora_do_main",
}


class EstadoMedicao(StrEnum):
    MEDIDO = "MEDIDO"
    NAO_MEDIDO = "NAO_MEDIDO"


class Cache(StrEnum):
    FRIO = "FRIO"
    QUENTE = "QUENTE"
    NAO_CONTROLADO = "NAO_CONTROLADO"


@dataclass(frozen=True)
class Etapa:
    nome: str
    executar: Callable[[], object] | None
    saida: Path | None = None
    motivo_ausencia: str = ""


@dataclass(frozen=True)
class Medicao:
    etapa: str
    estado: EstadoMedicao
    motivo: str
    cache: Cache
    repeticoes: int
    tempos_ns: tuple[int, ...]
    pico_python_bytes: int | None
    rss_max_kib: int | None
    armazenamento_bytes: int | None


def etapa_pendente(nome: str) -> Etapa:
    """Etapa ainda sem implementação no main; a medição sai NAO_MEDIDO com o motivo.

    Raises:
        KeyError: etapa fora de `ETAPAS_PENDENTES`.
    """
    return Etapa(nome, None, motivo_ausencia=ETAPAS_PENDENTES[nome])


def _nao_medido(etapa: Etapa, motivo: str, cache: Cache) -> Medicao:
    logger.info("desempenho_nao_medido etapa=%s motivo=%s", etapa.nome, motivo)
    return Medicao(
        etapa=etapa.nome,
        estado=EstadoMedicao.NAO_MEDIDO,
        motivo=motivo,
        cache=cache,
        repeticoes=0,
        tempos_ns=(),
        pico_python_bytes=None,
        rss_max_kib=None,
        armazenamento_bytes=None,
    )


def _armazenamento(saida: Path | None) -> int | None:
    if saida is None or not saida.exists():
        return None
    return sum(c.stat().st_size for c in saida.rglob("*") if c.is_file())


def _executar_uma(etapa: Etapa, relogio: Callable[[], int]) -> tuple[int, int]:
    executar = etapa.executar
    if executar is None:
        raise ValueError(f"etapa_sem_execucao etapa={etapa.nome}")
    tracemalloc.start()
    try:
        inicio = relogio()
        executar()
        fim = relogio()
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return fim - inicio, pico


def medir(
    etapa: Etapa,
    *,
    repeticoes: int = 3,
    cache: Cache = Cache.NAO_CONTROLADO,
    relogio: Callable[[], int] = time.perf_counter_ns,
) -> Medicao:
    """Executa a etapa `repeticoes` vezes e registra tempo, pico de memória e armazenamento.

    O pico de memória Python vem do `tracemalloc` (não inclui buffers nativos do DuckDB); o RSS
    máximo do processo (`ru_maxrss`) cobre o resto, sem separar etapas do mesmo processo.

    Raises:
        ValueError: `repeticoes` menor que 1.
    """
    if repeticoes < 1:
        raise ValueError(f"repeticoes_invalidas repeticoes={repeticoes}")
    if etapa.executar is None:
        return _nao_medido(etapa, etapa.motivo_ausencia or "sem_execucao", cache)
    tempos: list[int] = []
    pico = 0
    for _ in range(repeticoes):
        try:
            tempo, pico_rodada = _executar_uma(etapa, relogio)
        except NotImplementedError:
            return _nao_medido(etapa, "nao_implementado", cache)
        tempos.append(tempo)
        pico = max(pico, pico_rodada)
    medicao = Medicao(
        etapa=etapa.nome,
        estado=EstadoMedicao.MEDIDO,
        motivo="",
        cache=cache,
        repeticoes=repeticoes,
        tempos_ns=tuple(tempos),
        pico_python_bytes=pico,
        rss_max_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        armazenamento_bytes=_armazenamento(etapa.saida),
    )
    logger.info("desempenho_medido etapa=%s repeticoes=%d cache=%s", etapa.nome, repeticoes, cache)
    return medicao


def gravar_relatorio(
    medicoes: Sequence[Medicao],
    out: Path,
    *,
    ambiente: Ambiente,
    instante: datetime,
    origem_dados: OrigemDados,
) -> Path:
    """Relatório JSON com ambiente, instante, origem dos dados, cache e repetições.

    Raises:
        ValueError: instante sem fuso UTC.
    """
    deslocamento = instante.utcoffset()
    if deslocamento is None or deslocamento.total_seconds() != 0:
        raise ValueError(f"instante_sem_utc instante={instante.isoformat()}")
    conteudo = {
        "instante": instante.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "origem_dados": origem_dados.value,
        "ambiente": ambiente.model_dump(mode="json"),
        "medicoes": [asdict(m) for m in medicoes],
    }
    out.mkdir(parents=True, exist_ok=True)
    destino = out / f"desempenho_{instante.strftime('%Y%m%dT%H%M%SZ')}.json"
    temporario = destino.with_name(f".{destino.name}.tmp")
    temporario.write_text(
        json.dumps(conteudo, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporario.replace(destino)
    logger.info("desempenho_relatorio destino=%s medicoes=%d", destino, len(medicoes))
    return destino
