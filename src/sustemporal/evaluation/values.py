"""Parcela identificada de valor de tabela não aprovado (T13, P3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, FamiliaRegra, Governanca, RuleSpec, RunResult

__all__ = [
    "CATEGORIAS",
    "COLUNAS_VALORES",
    "ESTRATOS_COM_RAZAO",
    "SCHEMA_VALORES",
    "summarize_values",
]

SCHEMA_VALORES = "valores_p3.v1"
COLUNAS_VALORES = (
    "run_id",
    "estrato",
    "categoria",
    "aditiva",
    "ocorrencias",
    "valor_apresentado",
    "valor_aprovado",
    "diferenca",
    "razao",
)
ESTRATOS_COM_RAZAO = ("NAO_APROVADO", "APROVADO_PARCIAL")
CATEGORIAS = (
    "IDENTIFICADA_GOVERNANCA_MUNICIPAL",
    "INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA",
    "INCONCLUSIVO",
    "SEM_VIOLACAO_VERIFICADA",
    "DIFERENCA_NEGATIVA",
    "CAMPOS_INSUFICIENTES",
    "ROTULO_CONTRADITORIO",
)


def summarize_values(
    run: RunResult,
    labels: DatasetRef,
    out: Path,
    *,
    regras: Sequence[RuleSpec] | None = None,
    governanca_por_familia: Mapping[FamiliaRegra, Governanca] | None = None,
) -> DatasetRef:
    """Soma d(r) uma vez por ocorrência, com categorias de exclusão explícitas."""
    raise NotImplementedError
