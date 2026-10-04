"""Afirmações e texto legível por templates fixos (sem LLM)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts.explanation import Afirmacao, Evidence
    from sustemporal.contracts.rules import RuleEvaluation


class TemplateInvalido(ValueError):
    """Template desconhecido ou sem referência resolvível no bundle."""


def carregar_templates() -> dict[str, object]:
    raise NotImplementedError


def afirmar(
    template_id: str, avaliacao: RuleEvaluation, *, evidencias: Mapping[str, Evidence]
) -> Afirmacao:
    raise NotImplementedError
