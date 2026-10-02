"""Partições temporais da coorte (T10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import CohortSpec, DatasetRef, SplitManifest


def build_splits(dataset: DatasetRef, cohort: CohortSpec, out: Path) -> SplitManifest:
    """Separa desenvolvimento, calibração e teste por competência de processamento."""
    raise NotImplementedError
