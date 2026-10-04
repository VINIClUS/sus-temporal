"""Harness de desempenho (T13): tempo, memória e armazenamento com ambiente, cache e repetições."""

from __future__ import annotations

import time
from dataclasses import dataclass
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
    """Etapa ainda sem implementação no main; a medição sai NAO_MEDIDO com o motivo."""
    raise NotImplementedError


def medir(
    etapa: Etapa,
    *,
    repeticoes: int = 3,
    cache: Cache = Cache.NAO_CONTROLADO,
    relogio: Callable[[], int] = time.perf_counter_ns,
) -> Medicao:
    """Executa a etapa `repeticoes` vezes e registra tempo, pico de memória e armazenamento."""
    raise NotImplementedError


def gravar_relatorio(
    medicoes: Sequence[Medicao],
    out: Path,
    *,
    ambiente: Ambiente,
    instante: datetime,
    origem_dados: OrigemDados,
) -> Path:
    """Relatório JSON com ambiente, instante, cache e repetições de cada medição."""
    raise NotImplementedError
