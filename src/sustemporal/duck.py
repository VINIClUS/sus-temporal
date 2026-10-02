"""Conexão DuckDB offline configurada pelo `RuntimeConfig` e citação segura de identificadores."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from sustemporal.contracts.config import RuntimeConfig

__all__ = ["conectar", "identificador_seguro"]

logger = logging.getLogger(__name__)

_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]*")


def conectar(
    runtime: RuntimeConfig, *, banco: str = ":memory:", temporario: Path | None = None
) -> duckdb.DuckDBPyConnection:
    """Abre o DuckDB com os limites do runtime, sem instalar nem carregar extensões sozinho.

    Returns:
        Conexão aberta; fechá-la cabe ao chamador.
    """
    config: dict[str, str | bool | int | float | list[str]] = {
        "memory_limit": runtime.duckdb_memoria,
        "threads": runtime.duckdb_threads,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    }
    if temporario is not None:
        config["temp_directory"] = str(temporario)
    con = duckdb.connect(banco, config=config)
    logger.info(
        "duckdb_conectado banco=%s threads=%d memoria=%s temporario=%s",
        banco,
        runtime.duckdb_threads,
        runtime.duckdb_memoria,
        temporario,
    )
    return con


def identificador_seguro(nome: str, permitidos: Collection[str]) -> str:
    """Cita um identificador SQL presente na allowlist e no padrão `[a-z_][a-z0-9_]*`.

    Raises:
        ValueError: nome fora da allowlist ou do padrão.
    """
    if _IDENTIFICADOR.fullmatch(nome) is None or nome not in permitidos:
        raise ValueError(f"identificador_nao_permitido nome={nome!r}")
    return f'"{nome}"'
