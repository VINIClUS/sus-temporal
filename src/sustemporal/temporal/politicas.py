"""Políticas temporais do catálogo (`catalog/policies/<politica_id>.yaml`)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts.temporal import PoliticaTemporal

__all__ = ["DIRETORIO_POLITICAS", "carregar_politica"]

DIRETORIO_POLITICAS = Path("catalog/policies")


def carregar_politica(politica_id: str, diretorio: Path = DIRETORIO_POLITICAS) -> PoliticaTemporal:
    raise NotImplementedError
