"""Colunas obrigatórias de cada entrada do `validate --ingest`, conferidas antes de gravar (T07)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.duck import identificador_seguro
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente

if TYPE_CHECKING:
    import duckdb

    from sustemporal.contracts.records import DatasetRef

__all__ = ["exigir_colunas_obrigatorias"]


def _fora_do_esquema(ref: DatasetRef, coluna: str, motivo: str, linhas: int) -> ConteudoDivergente:
    return ConteudoDivergente(
        f"entrada_fora_do_esquema schema={ref.schema_id} dataset={ref.dataset_id} "
        f"coluna={coluna} motivo={motivo} linhas={linhas}"
    )


def exigir_colunas_obrigatorias(
    con: duckdb.DuckDBPyConnection, ref: DatasetRef, presentes: set[str]
) -> None:
    """Toda coluna não anulável do esquema existe no arquivo e nenhuma linha a tem nula.

    Raises:
        ConteudoDivergente: coluna ausente (`motivo=ausente`, todas as linhas) ou com nulos
            (`motivo=nulo`), na ordem das colunas do esquema.
    """
    obrigatorias = [c.nome for c in carregar_esquema(ref.schema_id).colunas if not c.anulavel]
    for nome in obrigatorias:
        if nome not in presentes:
            raise _fora_do_esquema(ref, nome, "ausente", ref.linhas)
    contagens = ", ".join(
        f"count(*) FILTER (WHERE {identificador_seguro(nome, obrigatorias)} IS NULL)"
        for nome in obrigatorias
    )
    nulos = con.execute(
        f"SELECT {contagens} FROM read_parquet($c)",  # noqa: S608
        {"c": ref.caminho},
    ).fetchall()[0]
    for nome, linhas in zip(obrigatorias, nulos, strict=True):
        if linhas:
            raise _fora_do_esquema(ref, nome, "nulo", int(linhas))
