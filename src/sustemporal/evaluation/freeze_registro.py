"""Registro append-only das avaliações, com resultados nulos e correções declaradas (T11)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts import EvaluationReport

__all__ = ["ler_registro", "registrar_execucao"]


def ler_registro(registro: Path) -> list[dict[str, Any]]:
    """Entradas do registro, conferindo o encadeamento de cada linha com a anterior."""
    raise NotImplementedError


def registrar_execucao(
    registro: Path,
    relatorio: EvaluationReport,
    *,
    corrige: str | None = None,
    declaracao: str | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Acrescenta uma entrada; nunca reescreve nem apaga as anteriores."""
    raise NotImplementedError
