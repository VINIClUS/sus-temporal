"""Seleção em lote no DuckDB, equivalente à seleção por registro (`selecao_versoes.v1`)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    import duckdb

    from sustemporal.contracts.base import OrigemDados
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import PoliticaTemporal
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["TABELA", "gravar_selecoes", "selecionar_lote"]

TABELA = "selecao_versoes"


def selecionar_lote(
    con: duckdb.DuckDBPyConnection,
    registros: str,
    regras: list[RuleSpec],
    politica: PoliticaTemporal,
    registro: RegistroTemporal,
    *,
    run_id: str,
    uf: str | None = None,
    corte: datetime | None = None,
) -> None:
    """Cria `selecao_versoes` a partir da tabela `registros` (row_id e as duas competências)."""
    raise NotImplementedError


def gravar_selecoes(
    con: duckdb.DuckDBPyConnection, destino: Path, *, run_id: str, origem: OrigemDados
) -> DatasetRef:
    raise NotImplementedError
