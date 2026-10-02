"""Download verificável e promoção atômica de artefatos (T02)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from sustemporal.acquisition.transport import Transporte
    from sustemporal.contracts import ArtifactObservation, SourceRequest

NOME_MANIFESTO = "manifesto.jsonl"


def agora_utc() -> datetime:
    return datetime.now(UTC)


def fetch_source(
    request: SourceRequest,
    store: Path,
    *,
    rede_permitida: bool = False,
    relogio: Callable[[], datetime] = agora_utc,
    transportes: Mapping[str, Transporte] | None = None,
    manifesto: Path | None = None,
) -> ArtifactObservation:
    """Obtém uma fonte e registra a observação da tentativa, inclusive quando falha.

    Raises:
        RedeProibida: ftp/https com `rede_permitida` falso (a recusa fica registrada).
    """
    raise NotImplementedError


def nomes_listados(store: Path, observacao: ArtifactObservation) -> list[str]:
    """Nomes de uma listagem de diretório obtida, lidos dos bytes guardados."""
    raise NotImplementedError
