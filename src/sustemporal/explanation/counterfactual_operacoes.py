"""Catálogo fechado de operações cadastrais do CNES e seus efeitos simulados (T09)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts import OperationSpec

__all__ = ["CATALOGO_OPERACOES", "carregar_operacoes"]

CATALOGO_OPERACOES = Path(__file__).resolve().parents[3] / "catalog" / "operations.yaml"


def carregar_operacoes(caminho: Path = CATALOGO_OPERACOES) -> tuple[OperationSpec, ...]:
    """Operações do catálogo, validadas pelo contrato e pelos efeitos conhecidos."""
    raise NotImplementedError
