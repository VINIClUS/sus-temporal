"""Conexão DuckDB offline configurada pelo `RuntimeConfig` e citação segura de identificadores."""

from __future__ import annotations

import atexit
import contextlib
import functools
import logging
import re
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from collections.abc import Collection

    from sustemporal.contracts.config import RuntimeConfig

__all__ = ["conectar", "identificador_seguro"]

logger = logging.getLogger(__name__)

_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]*")


def _remover_se_vazia(raiz: Path) -> None:
    with contextlib.suppress(OSError):
        raiz.rmdir()


@functools.cache
def _raiz_temporaria() -> Path:
    raiz = Path(tempfile.mkdtemp(prefix="sustemporal_duckdb_"))
    atexit.register(_remover_se_vazia, raiz)
    return raiz


def _temporario_padrao() -> Path:
    # Subdiretório ainda inexistente: o DuckDB o cria ao precisar e o apaga ao fechar.
    return _raiz_temporaria() / f"conexao_{uuid.uuid4().hex}"


def conectar(
    runtime: RuntimeConfig, *, banco: str = ":memory:", temporario: Path | None = None
) -> duckdb.DuckDBPyConnection:
    """Abre o DuckDB com os limites do runtime, sem instalar nem carregar extensões sozinho.

    Sem `temporario`, o transbordo vai para um diretório próprio da conexão dentro de um
    diretório privado (0700) do sistema, nunca para `.tmp` no diretório atual.

    Returns:
        Conexão aberta; fechá-la cabe ao chamador.
    """
    destino = temporario if temporario is not None else _temporario_padrao()
    config: dict[str, str | bool | int | float | list[str]] = {
        "memory_limit": runtime.duckdb_memoria,
        "threads": runtime.duckdb_threads,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
        "temp_directory": str(destino),
    }
    con = duckdb.connect(banco, config=config)
    logger.info(
        "duckdb_conectado banco=%s threads=%d memoria=%s temporario=%s",
        banco,
        runtime.duckdb_threads,
        runtime.duckdb_memoria,
        destino,
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
