"""Bootstrap por conglomerado (estabelecimento ou bloco temporal) para razões (T11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np

    from sustemporal.contracts.evaluation import IntervaloConfianca
    from sustemporal.contracts.experiment import BootstrapSpec

__all__ = ["intervalo_razao", "reamostrar_razao"]


def reamostrar_razao(
    numeradores: Sequence[int],
    denominadores: Sequence[int],
    grupos: Sequence[str],
    spec: BootstrapSpec,
) -> np.ndarray:
    """Razões reamostradas sorteando conglomerados inteiros, nunca linhas isoladas."""
    raise NotImplementedError


def intervalo_razao(
    numeradores: Sequence[int],
    denominadores: Sequence[int],
    grupos: Sequence[str],
    spec: BootstrapSpec,
) -> IntervaloConfianca | None:
    """Intervalo percentil; None quando nenhuma réplica tem denominador positivo."""
    raise NotImplementedError
