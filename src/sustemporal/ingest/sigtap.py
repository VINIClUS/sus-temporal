"""Normalização das tabelas do SIGTAP (T04)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, DatasetRef, LayoutSpec


def normalize_sigtap(artifact: ArtifactVersion, layout: LayoutSpec, out: Path) -> DatasetRef:
    """Normaliza um pacote TabelaUnificada do SIGTAP."""
    raise NotImplementedError
