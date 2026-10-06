"""Bootstrap por conglomerado (estabelecimento ou bloco temporal) para razões (T11).

A unidade sorteada é o conglomerado inteiro: no bootstrap por estabelecimento, toda a trajetória
mensal do estabelecimento entra ou sai junta; na sensibilidade por blocos temporais, cada
competência é um bloco. Nenhuma das duas finge independência entre linhas, e nenhuma protege
contra toda forma de dependência ao mesmo tempo (a outra dimensão continua correlacionada).

A réplica com denominador zero fica fora dos percentis, e o intervalo registra quantas sobraram
(`replicas_validas`). Com menos de dois conglomerados de denominador positivo, toda réplica válida
repete a estimativa: a largura zero seria construção, não precisão, e o intervalo é nulo.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

import numpy as np

from sustemporal.contracts.evaluation import IntervaloConfianca

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sustemporal.contracts.experiment import BootstrapSpec

__all__ = ["intervalo_diferenca", "intervalo_razao", "reamostrar_razao"]

_CASAS = Decimal("0.000001")
_MINIMO_DE_CONGLOMERADOS = 2


def _somas_reamostradas(
    colunas: Sequence[Sequence[int]], grupos: Sequence[str], spec: BootstrapSpec
) -> list[np.ndarray]:
    rotulos = sorted(set(grupos))
    posicao = {grupo: i for i, grupo in enumerate(rotulos)}
    indice = np.array([posicao[g] for g in grupos], dtype=np.int64)
    gerador = np.random.default_rng(int(spec.semente))
    sorteio = gerador.integers(0, len(rotulos), size=(int(spec.reamostragens), len(rotulos)))
    saida = []
    for coluna in colunas:
        por_grupo = np.bincount(
            indice, weights=np.asarray(coluna, dtype=float), minlength=len(rotulos)
        )
        saida.append(por_grupo[sorteio].sum(axis=1))
    return saida


def reamostrar_razao(
    numeradores: Sequence[int],
    denominadores: Sequence[int],
    grupos: Sequence[str],
    spec: BootstrapSpec,
) -> np.ndarray:
    """Razões reamostradas sorteando conglomerados inteiros, nunca linhas isoladas.

    Réplica com denominador zero vira NaN.
    """
    if not grupos:
        return np.full(int(spec.reamostragens), np.nan)
    numerador, denominador = _somas_reamostradas([numeradores, denominadores], grupos, spec)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denominador > 0, numerador / denominador, np.nan)


def _estimavel(denominadores: Sequence[int], grupos: Sequence[str]) -> bool:
    positivos = {g for g, d in zip(grupos, denominadores, strict=True) if d > 0}
    return len(positivos) >= _MINIMO_DE_CONGLOMERADOS


def _intervalo(replicas: np.ndarray, spec: BootstrapSpec) -> IntervaloConfianca | None:
    validas = replicas[~np.isnan(replicas)]
    if validas.size == 0:
        return None
    cauda = (1 - float(spec.confianca)) / 2
    inferior, superior = np.quantile(validas, [cauda, 1 - cauda])
    return IntervaloConfianca(
        inferior=Decimal(repr(float(inferior))).quantize(_CASAS, rounding=ROUND_HALF_EVEN),
        superior=Decimal(repr(float(superior))).quantize(_CASAS, rounding=ROUND_HALF_EVEN),
        nivel=spec.confianca,
        replicas_validas=int(validas.size),
    )


def intervalo_razao(
    numeradores: Sequence[int],
    denominadores: Sequence[int],
    grupos: Sequence[str],
    spec: BootstrapSpec,
) -> IntervaloConfianca | None:
    """Intervalo percentil; None com menos de dois conglomerados de denominador positivo."""
    if not _estimavel(denominadores, grupos):
        return None
    return _intervalo(reamostrar_razao(numeradores, denominadores, grupos, spec), spec)


def intervalo_diferenca(
    numeradores_a: Sequence[int],
    numeradores_b: Sequence[int],
    denominadores: Sequence[int],
    grupos: Sequence[str],
    spec: BootstrapSpec,
) -> IntervaloConfianca | None:
    """Intervalo da diferença pareada (a − b)/denominador, com o mesmo sorteio para os dois.

    None com menos de dois conglomerados de denominador positivo.
    """
    if not _estimavel(denominadores, grupos):
        return None
    a, b, denominador = _somas_reamostradas(
        [numeradores_a, numeradores_b, denominadores], grupos, spec
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        replicas = np.where(denominador > 0, (a - b) / denominador, np.nan)
    return _intervalo(replicas, spec)
