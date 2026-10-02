"""Métricas pareadas com denominadores explícitos (T11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, EvaluationReport, RunResult, SplitManifest


def evaluate_runs(
    runs: list[RunResult], labels: DatasetRef, split: SplitManifest, out: Path
) -> EvaluationReport:
    """Calcula as métricas do protocolo para as execuções comparadas."""
    raise NotImplementedError
