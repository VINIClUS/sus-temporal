"""Carga e validação do catálogo formal de regras (`catalog/rules/**/*.yaml`) e do SQL associado."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts.rules import RuleSpec

__all__ = ["CATALOGO_REGRAS", "carregar_regras"]

CATALOGO_REGRAS = Path(__file__).resolve().parents[3] / "catalog" / "rules"


def carregar_regras(raiz: Path = CATALOGO_REGRAS) -> list[RuleSpec]:
    """Regras do catálogo validadas contra famílias, esquemas e SQL."""
    raise NotImplementedError
