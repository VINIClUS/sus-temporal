"""Reprodução offline a partir de originais locais (T14)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import EvaluationReport, RunConfig


def reproduce(config: RunConfig, out: Path) -> EvaluationReport:
    """Reexecuta o fluxo congelado e compara hashes lógicos e métricas."""
    raise NotImplementedError
