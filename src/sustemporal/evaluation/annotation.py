"""Amostra estratificada para avaliação humana cega (T12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import AnnotationSample, DatasetRef, RunConfig, SplitManifest


def prepare_annotation_sample(
    labels: DatasetRef, split: SplitManifest, config: RunConfig, out: Path
) -> AnnotationSample:
    """Sorteia a amostra estratificada e prepara pacotes sem saídas do motor."""
    raise NotImplementedError
