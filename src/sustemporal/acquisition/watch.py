"""Observação de republicações em janela móvel (T13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.acquisition.fetch import agora_utc

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime
    from pathlib import Path

    from sustemporal.acquisition.comparacao import ComparacaoVersoes
    from sustemporal.acquisition.transport import Transporte
    from sustemporal.contracts import ArtifactObservation, SourceRequest

__all__ = ["observe_updates", "resumir_vigilancia"]


def observe_updates(
    requests: list[SourceRequest],
    store: Path,
    *,
    rede_permitida: bool = False,
    relogio: Callable[[], datetime] = agora_utc,
    transportes: Mapping[str, Transporte] | None = None,
    manifesto: Path | None = None,
) -> list[ArtifactObservation]:
    """Observa cada requisição e preserva também tentativas sem mudança."""
    raise NotImplementedError("observe_updates")


def resumir_vigilancia(
    observacoes: Sequence[ArtifactObservation], comparacoes: Sequence[ComparacaoVersoes]
) -> str:
    raise NotImplementedError("resumir_vigilancia")
