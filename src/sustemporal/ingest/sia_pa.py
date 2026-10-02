"""Normalização do SIA-PA preservando multiplicidade (T03)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, DatasetRef, LayoutSpec


def normalize_pa(artifact: ArtifactVersion, layout: LayoutSpec, out: Path) -> DatasetRef:
    """Normaliza um artefato SIA-PA para o esquema canônico sia_pa.v1."""
    raise NotImplementedError
