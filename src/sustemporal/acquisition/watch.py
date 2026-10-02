"""Observação de republicações em janela móvel (T13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactObservation, SourceRequest


def observe_updates(requests: list[SourceRequest], store: Path) -> list[ArtifactObservation]:
    """Observa cada requisição e preserva também tentativas sem mudança."""
    raise NotImplementedError
