"""Conferência do conteúdo lido contra o `DatasetRef` declarado (linhas e hash lógico)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sustemporal.duck import identificador_seguro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    import duckdb

    from sustemporal.contracts.records import DatasetRef

__all__ = ["ConteudoDivergente", "verificar_conteudo"]

logger = logging.getLogger(__name__)

_TABELA = "conferencia_conteudo"


class ConteudoDivergente(ValueError):
    """Arquivo cujo conteúdo não corresponde às linhas ou ao hash lógico do `DatasetRef`."""


def verificar_conteudo(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    """Confere linhas e hash lógico (colunas do esquema presentes, na ordem do esquema).

    Raises:
        ConteudoDivergente: contagem ou hash diferente do declarado.
    """
    descricao = con.execute(
        "DESCRIBE SELECT * FROM read_parquet($c)", {"c": dataset.caminho}
    ).fetchall()
    fisicas = {str(linha[0]) for linha in descricao}
    colunas = [c.nome for c in carregar_esquema(dataset.schema_id).colunas if c.nome in fisicas]
    projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {_TABELA} AS SELECT {projecao} "  # noqa: S608
        "FROM read_parquet($c)",
        {"c": dataset.caminho},
    )
    try:
        linhas = int(con.execute(f"SELECT count(*) FROM {_TABELA}").fetchall()[0][0])  # noqa: S608
        hash_obtido = hash_logico_relacao(con, _TABELA, colunas)
    finally:
        con.execute(f"DROP TABLE IF EXISTS {_TABELA}")
    if linhas != dataset.linhas or hash_obtido != dataset.hash_logico:
        raise ConteudoDivergente(
            f"conteudo_divergente schema={dataset.schema_id} "
            f"esperado={dataset.linhas}:{dataset.hash_logico} obtido={linhas}:{hash_obtido}"
        )
    logger.info("conteudo_conferido schema=%s linhas=%d", dataset.schema_id, linhas)
