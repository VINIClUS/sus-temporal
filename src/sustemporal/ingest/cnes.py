"""Normalização de arquivos do CNES (T04)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, DatasetRef, LayoutSpec


def normalize_cnes(artifact: ArtifactVersion, layout: LayoutSpec, out: Path) -> DatasetRef:
    """Normaliza um artefato do CNES para o esquema canônico da família."""
    raise NotImplementedError
