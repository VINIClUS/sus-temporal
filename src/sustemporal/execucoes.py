"""Lugar único das execuções do `validate`: `<raiz_saidas>/runs/<run_id>/`."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.config import RunConfig

__all__ = ["DIRETORIO_EXECUCOES", "raiz_execucoes"]

DIRETORIO_EXECUCOES = "runs"


def raiz_execucoes(config: RunConfig) -> Path:
    """Raiz das execuções: `<raiz_saidas>/runs`."""
    raise NotImplementedError
