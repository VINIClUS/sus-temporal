"""Parcela identificada de valor de tabela não aprovado (T13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, RunResult


def summarize_values(run: RunResult, labels: DatasetRef, out: Path) -> DatasetRef:
    """Soma d(r) uma vez por ocorrência, com categorias de exclusão explícitas."""
    raise NotImplementedError
