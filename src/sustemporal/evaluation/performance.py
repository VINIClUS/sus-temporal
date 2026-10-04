"""Harness de desempenho (T13): tempo, memória e armazenamento com ambiente, cache e repetições.

Mede só etapas executáveis. Etapa ainda não montada no harness (contrafactuais do T09) ou sem
implementação no main (métricas do T11), ou stub que levanta `NotImplementedError`, sai
`NAO_MEDIDO` com motivo, nunca com número inventado. A escala DRS XI/SP roda na máquina do pesquisador (marcador `perf`, fora do CI).
"""

from __future__ import annotations

import json
import logging
import resource
import sys
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
    "contrafactuais": "T09_etapa_nao_montada_no_harness",
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
    cache_por_repeticao: tuple[Cache, ...]
    pico_python_bytes: int | None
    rss_max_processo_bytes: int | None
    armazenamento_bytes: int | None
    armazenamento_total_bytes: int | None


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
        cache_por_repeticao=(),
        pico_python_bytes=None,
        rss_max_processo_bytes=None,
        armazenamento_bytes=None,
        armazenamento_total_bytes=None,
    )


def _armazenamento(saida: Path | None) -> int | None:
    if saida is None or not saida.exists():
        return None
    return sum(c.stat().st_size for c in saida.rglob("*") if c.is_file())


def _rss_max_bytes() -> int:
    """Pico de RSS do processo inteiro (não por etapa); KiB no Linux, bytes no macOS."""
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(pico) if sys.platform == "darwin" else int(pico) * 1024


def _cronometrar(executar: Callable[[], object], relogio: Callable[[], int]) -> int:
    inicio = relogio()
    executar()
    return relogio() - inicio


def _pico_python(executar: Callable[[], object]) -> int | None:
    """Rodada extra só para memória; não interfere num tracemalloc já ativo de quem chama."""
    if tracemalloc.is_tracing():
        return None
    tracemalloc.start()
    try:
        executar()
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return pico


def _caches(cache: Cache, repeticoes: int) -> tuple[Cache, ...]:
    if cache is Cache.FRIO:
        return (Cache.FRIO, *(Cache.QUENTE,) * (repeticoes - 1))
    return (cache,) * repeticoes


def medir(
    etapa: Etapa,
    *,
    repeticoes: int = 3,
    cache: Cache = Cache.NAO_CONTROLADO,
    relogio: Callable[[], int] = time.perf_counter_ns,
) -> Medicao:
    """Executa a etapa `repeticoes` vezes cronometradas e uma rodada extra para memória.

    O tempo é medido sem `tracemalloc`. O pico de memória Python vem da rodada extra (não inclui
    buffers nativos do DuckDB) e fica nulo se quem chama já usa `tracemalloc`. O RSS máximo é do
    processo inteiro. O armazenamento é o que o diretório de saída ganhou durante a medição; o
    total também é registrado. Com cache `FRIO`, só a primeira repetição é fria.

    Raises:
        ValueError: `repeticoes` menor que 1.
    """
    if repeticoes < 1:
        raise ValueError(f"repeticoes_invalidas repeticoes={repeticoes}")
    executar = etapa.executar
    if executar is None:
        return _nao_medido(etapa, etapa.motivo_ausencia or "sem_execucao", cache)
    antes = _armazenamento(etapa.saida) or 0
    try:
        tempos = tuple(_cronometrar(executar, relogio) for _ in range(repeticoes))
        pico = _pico_python(executar)
    except NotImplementedError:
        return _nao_medido(etapa, "nao_implementado", cache)
    total = _armazenamento(etapa.saida)
    medicao = Medicao(
        etapa=etapa.nome,
        estado=EstadoMedicao.MEDIDO,
        motivo="" if pico is not None else "memoria_nao_medida_tracemalloc_ativo",
        cache=cache,
        repeticoes=repeticoes,
        tempos_ns=tempos,
        cache_por_repeticao=_caches(cache, repeticoes),
        pico_python_bytes=pico,
        rss_max_processo_bytes=_rss_max_bytes(),
        armazenamento_bytes=None if total is None else total - antes,
        armazenamento_total_bytes=total,
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
