"""Métricas pareadas sobre linhas já avaliadas, com denominadores explícitos (T11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sustemporal.contracts.evaluation import ValorMetrica

__all__ = ["LinhaAvaliada", "Situacao", "calcular_metricas"]


class Situacao(StrEnum):
    ALERTA = "ALERTA"
    SEM_ALERTA = "SEM_ALERTA"
    ABSTENCAO = "ABSTENCAO"


@dataclass(frozen=True)
class LinhaAvaliada:
    """Registro da população com rótulo, estratos e a situação de cada método."""

    row_id: str
    rotulo: str | None
    cnes: str | None
    competencia: str | None
    instrumento: str | None
    situacoes: Mapping[str, Situacao] = field(default_factory=dict)
    no_dominio_comum: bool = False
    causa: str | None = None


def calcular_metricas(
    linhas: Sequence[LinhaAvaliada],
    metodos: Sequence[str],
    *,
    pares: Sequence[tuple[str, str]] = (),
) -> list[ValorMetrica]:
    """Métricas por método e estrato, divergências pareadas e domínio comum."""
    raise NotImplementedError
