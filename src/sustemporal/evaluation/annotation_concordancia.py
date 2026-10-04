"""Concordância antes da adjudicação, referência humana e comparação com o motor (T12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.errors import ErroSustemporal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from fractions import Fraction

    from sustemporal.contracts import (
        AnnotationSample,
        AvaliacaoCaso,
        FamiliaRegra,
        ReferenciaHumana,
    )

__all__ = [
    "ReferenciaNaoFechada",
    "RelatorioConcordancia",
    "comparar_com_motor",
    "concordancia",
    "estimar_horas",
    "fechar_referencia",
    "kappa_cohen",
]


class ReferenciaNaoFechada(ErroSustemporal):
    """Comparação com o motor tentada antes de a referência humana ser fechada."""


@dataclass(frozen=True)
class RelatorioConcordancia:
    casos: int
    bruta: Fraction
    kappa: Fraction | None
    por_familia: dict[str, tuple[Fraction, Fraction | None]]


def kappa_cohen(pares: Sequence[tuple[str, str]]) -> Fraction | None:
    """κ de Cohen exato; None quando a concordância esperada é 1."""
    raise NotImplementedError


def concordancia(
    amostra: AnnotationSample,
    mapa: Mapping[str, str],
    avaliador_a: Iterable[AvaliacaoCaso],
    avaliador_b: Iterable[AvaliacaoCaso],
) -> RelatorioConcordancia:
    """Concordância bruta e κ, global e por família, antes da adjudicação."""
    raise NotImplementedError


def fechar_referencia(
    amostra: AnnotationSample,
    mapa: Mapping[str, str],
    avaliador_a: Iterable[AvaliacaoCaso],
    avaliador_b: Iterable[AvaliacaoCaso],
    adjudicacoes: Iterable[AvaliacaoCaso] = (),
) -> ReferenciaHumana:
    """Consenso ou adjudicação cega por caso; pendências deixam a referência ABERTA."""
    raise NotImplementedError


def comparar_com_motor(
    referencia: ReferenciaHumana, familias_motor: Mapping[str, frozenset[FamiliaRegra]]
) -> dict[str, int]:
    """Contagens por categoria de comparação; recusa referência ABERTA."""
    raise NotImplementedError


def estimar_horas(
    minutos_por_caso: Fraction, *, casos: int = 400, avaliadores: int = 2
) -> Fraction:
    """Planejamento: avaliadores × casos × minutos / 60, sem a adjudicação."""
    raise NotImplementedError
