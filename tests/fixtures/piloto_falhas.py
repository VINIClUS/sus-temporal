"""Normalizador sintético que falha fora dos tipos de quarentena (SINTETICO)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, DatasetRef, LayoutSpec

__all__ = ["normalizar_com_erro"]


def normalizar_com_erro(
    artifact: ArtifactVersion, layout: LayoutSpec, out: Path, **_extras: object
) -> DatasetRef:
    raise ValueError(f"falha_sintetica id={artifact.artifact_id} layout={layout.layout_id}")
