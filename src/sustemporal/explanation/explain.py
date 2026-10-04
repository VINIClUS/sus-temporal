"""Explicações com evidência rastreável (T08)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts import ExplanationBundle, RuleSpec, RunResult


class ExplicacaoIndisponivel(ValueError):
    """Execução, saída ou registro que não permite montar a explicação."""


def montar_explicacao(
    run: RunResult, row_id: str, *, regras: list[RuleSpec] | None = None
) -> object:
    raise NotImplementedError


def explain(
    run: RunResult, row_id: str, *, regras: list[RuleSpec] | None = None
) -> ExplanationBundle:
    """Monta o pacote de explicação de um registro avaliado."""
    raise NotImplementedError
