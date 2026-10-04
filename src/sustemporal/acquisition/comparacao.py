"""Comparação de duas versões de conteúdo de um arquivo publicado (T13).

As duas versões são normalizadas para o esquema canônico e comparadas como multiconjuntos de
linhas, sem as colunas de linhagem física. Linhas nunca são casadas por posição: sem
identificador longitudinal, a comparação só conta linhas que saíram e que entraram.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, LayoutSpec
    from sustemporal.contracts.base import OrigemDados
    from sustemporal.contracts.config import RuntimeConfig

__all__ = ["ComparacaoVersoes", "ResultadoComparacao", "comparar_versoes"]


class ResultadoComparacao(StrEnum):
    INALTERADA = "INALTERADA"
    REVISAO_REAL = "REVISAO_REAL"
    CORRESPONDENCIA_AMBIGUA = "CORRESPONDENCIA_AMBIGUA"


@dataclass(frozen=True)
class ComparacaoVersoes:
    anterior: str
    nova: str
    resultado: ResultadoComparacao
    linhas_removidas: int
    linhas_adicionadas: int
    motivo: str


def comparar_versoes(
    anterior: ArtifactVersion,
    nova: ArtifactVersion,
    *,
    layout: LayoutSpec,
    runtime: RuntimeConfig,
    destino: Path,
    origem_dados: OrigemDados,
) -> ComparacaoVersoes:
    raise NotImplementedError("comparar_versoes")
