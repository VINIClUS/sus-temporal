"""Classificador histórico e controle trivial (T10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import FeatureSpec, RunConfig, RunResult, SplitManifest


def fit_baseline(
    split: SplitManifest, features: FeatureSpec, config: RunConfig, out: Path
) -> RunResult:
    """Ajusta o baseline apenas com dados de treino e calibração."""
    raise NotImplementedError
