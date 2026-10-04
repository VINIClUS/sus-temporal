"""Alocação proporcional por estrato e sorteio reprodutível pela semente (T12)."""

from __future__ import annotations

import random
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from math import floor
from typing import TYPE_CHECKING

from sustemporal.contracts import Estrato

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["ESCALA_PROBABILIDADE", "alocar", "embaralhar", "estratos", "sortear"]

ESCALA_PROBABILIDADE = Decimal("1e-12")


def _acrescentar(aloc: dict[str, int], alvo: dict[str, Fraction], pop: Mapping[str, int]) -> None:
    candidatos = [h for h in sorted(aloc) if aloc[h] < pop[h]]
    escolhido = min(candidatos, key=lambda h: (-(alvo[h] - aloc[h]), h))
    aloc[escolhido] += 1


def _retirar(aloc: dict[str, int], alvo: dict[str, Fraction]) -> None:
    candidatos = [h for h in sorted(aloc) if aloc[h] > 1]
    escolhido = min(candidatos, key=lambda h: (-(aloc[h] - alvo[h]), h))
    aloc[escolhido] -= 1


def alocar(populacoes: Mapping[str, int], tamanho: int) -> dict[str, int]:
    """Alocação proporcional com ao menos um caso por estrato e soma exata `tamanho`.

    Raises:
        ValueError: tamanho não positivo, estrato vazio ou mais estratos que casos.
    """
    if tamanho < 1:
        raise ValueError(f"tamanho_invalido tamanho={tamanho}")
    if any(n < 1 for n in populacoes.values()):
        raise ValueError("estrato_vazio")
    total = sum(populacoes.values())
    if tamanho >= total:
        return dict(populacoes)
    if len(populacoes) > tamanho:
        raise ValueError(f"estratos_excedem_tamanho estratos={len(populacoes)} tamanho={tamanho}")
    alvo = {h: Fraction(tamanho * n, total) for h, n in populacoes.items()}
    aloc = {h: min(n, max(1, floor(alvo[h]))) for h, n in populacoes.items()}
    while sum(aloc.values()) < tamanho:
        _acrescentar(aloc, alvo, populacoes)
    while sum(aloc.values()) > tamanho:
        _retirar(aloc, alvo)
    return aloc


def sortear(
    membros: Mapping[str, Sequence[str]], alocacao: Mapping[str, int], semente: int
) -> dict[str, list[str]]:
    """Amostra aleatória simples sem reposição em cada estrato, semeada por estrato."""
    sorteio: dict[str, list[str]] = {}
    for estrato in sorted(alocacao):
        gerador = random.Random(f"{semente}:{estrato}")  # noqa: S311
        sorteio[estrato] = sorted(gerador.sample(sorted(membros[estrato]), alocacao[estrato]))
    return sorteio


def embaralhar(itens: Sequence[str], semente: int, rotulo: str) -> list[str]:
    """Ordem de apresentação independente do estrato, reprodutível pela semente."""
    ordem = sorted(itens)
    random.Random(f"{semente}:{rotulo}").shuffle(ordem)  # noqa: S311
    return ordem


def estratos(populacoes: Mapping[str, int], alocacao: Mapping[str, int]) -> tuple[Estrato, ...]:
    return tuple(
        Estrato(
            nome=nome,
            populacao=populacoes[nome],
            amostra=alocacao[nome],
            prob_inclusao=(Decimal(alocacao[nome]) / Decimal(populacoes[nome])).quantize(
                ESCALA_PROBABILIDADE, rounding=ROUND_HALF_EVEN
            ),
        )
        for nome in sorted(populacoes)
    )
