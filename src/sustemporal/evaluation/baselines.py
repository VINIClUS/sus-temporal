"""Classificador histórico e controle trivial (T10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.gates import DIR_DECISOES

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts import (
        DatasetRef,
        FeatureSpec,
        RunConfig,
        RunResult,
        SplitManifest,
    )


def fit_baseline(
    split: SplitManifest,
    features: FeatureSpec,
    config: RunConfig,
    out: Path,
    *,
    rotulos: DatasetRef | None = None,
    relogio: Callable[[], datetime] | None = None,
    decisoes: Path = DIR_DECISOES,
) -> RunResult:
    """Ajusta o baseline apenas com dados de treino e calibração."""
    raise NotImplementedError
