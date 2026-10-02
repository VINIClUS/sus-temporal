"""Relatório do piloto de observabilidade (T05)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import CohortSpec, DatasetRef, EvaluationReport


def build_pilot_report(
    datasets: list[DatasetRef], cohort: CohortSpec, out: Path
) -> EvaluationReport:
    """Produz contagens, ausências, defasagens e disponibilidade por estrato."""
    raise NotImplementedError
