"""Explicações com evidência rastreável (T08)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts import ExplanationBundle, RunResult


def explain(run: RunResult, row_id: str) -> ExplanationBundle:
    """Monta o pacote de explicação de um registro avaliado."""
    raise NotImplementedError
