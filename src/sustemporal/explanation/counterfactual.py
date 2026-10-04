"""Busca de contrafactuais com limites explícitos (T09)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sustemporal.contracts import (
        CounterfactualSearchResult,
        ExplanationBundle,
        OperationSpec,
        RunConfig,
    )
    from sustemporal.explanation.counterfactual_contexto import ContextoContrafactual

__all__ = ["search_counterfactuals"]


def search_counterfactuals(
    bundle: ExplanationBundle,
    config: RunConfig,
    *,
    contexto: ContextoContrafactual | None = None,
    operacoes: Sequence[OperationSpec] | None = None,
) -> CounterfactualSearchResult:
    """Busca operações cadastrais de menor custo e revalida o conjunto afetado."""
    raise NotImplementedError
