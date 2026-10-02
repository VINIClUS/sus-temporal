"""Motor SQL de avaliação de regras (T07)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, RuleSpec, RunConfig, RunResult, SnapshotSet
    from sustemporal.rules.insumos import InsumosAvaliacao


def evaluate_rules(
    dataset: DatasetRef,
    snapshots: SnapshotSet,
    rules: list[RuleSpec],
    config: RunConfig,
    out: Path,
    *,
    insumos: InsumosAvaliacao | None = None,
) -> RunResult:
    """Avalia as regras no conjunto de versões selecionado."""
    raise NotImplementedError
