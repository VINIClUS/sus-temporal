"""Partições temporais da coorte (T10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from sustemporal.contracts import CohortSpec, DatasetRef, SplitManifest, SplitSpec


def build_splits(
    dataset: DatasetRef,
    cohort: CohortSpec,
    out: Path,
    *,
    spec: SplitSpec | None = None,
    fonte_por_artefato: Mapping[str, str] | None = None,
    inspecionados: Iterable[str] = (),
) -> SplitManifest:
    """Separa desenvolvimento, calibração e teste por competência de processamento."""
    raise NotImplementedError
