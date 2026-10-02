"""Download verificável e promoção atômica de artefatos (T02)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactObservation, SourceRequest


def fetch_source(request: SourceRequest, store: Path) -> ArtifactObservation:
    """Obtém uma fonte e registra a observação da tentativa."""
    raise NotImplementedError
