"""Rótulos do PA_INDICA separados dos atributos (T03)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef


def label_pa(dataset: DatasetRef, codebook: Path, out: Path) -> DatasetRef:
    """Gera a tabela de rótulos preservando o valor bruto e a origem do código."""
    raise NotImplementedError
