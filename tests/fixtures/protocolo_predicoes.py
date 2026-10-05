"""Predições do baseline sem linhas do TESTE ou com linhas repetidas, SINTETICO (T11).

A cópia da execução tem saída própria e consistente com o `DatasetRef` (linhas e hash lógico):
só falta resultado de linhas do TESTE, ou há resultado repetido, o que a conferência de
conteúdo não pega.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.duck import conectar
from sustemporal.evaluation.baselines import SCHEMA_PREDICOES
from sustemporal.hashing import hash_logico_relacao

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import RunResult


def _do_teste(linhas: list[dict[str, Any]], metodo: str) -> list[dict[str, Any]]:
    do_metodo = [lin for lin in linhas if lin["metodo"] == metodo and lin["particao"] == "TESTE"]
    return sorted(do_metodo, key=lambda lin: lin["row_id"])


def _regravar(run: RunResult, destino: Path, linhas: list[dict[str, Any]]) -> RunResult:
    """Execução cuja saída de predições passa a ter `linhas`, com `DatasetRef` consistente."""
    (saida,) = run.saidas
    esquema = pq.read_table(saida.caminho).schema
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "predicoes.parquet"
    pq.write_table(pa.Table.from_pylist(linhas, schema=esquema), caminho)
    colunas = [c.nome for c in SCHEMA_PREDICOES.colunas]
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        con.execute("CREATE TABLE lida AS SELECT * FROM read_parquet($c)", {"c": str(caminho)})
        hash_logico = hash_logico_relacao(con, "lida", colunas)
    finally:
        con.close()
    nova = DatasetRef(
        dataset_id=calcular_dataset_id(saida.schema_id, hash_logico, saida.artifact_ids),
        schema_id=saida.schema_id,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=saida.artifact_ids,
        origem_dados=saida.origem_dados,
        produzido_por=saida.produzido_por,
    )
    return run.model_copy(update={"saidas": (nova,)})


def predicoes_sem_linhas_do_teste(
    run: RunResult, destino: Path, *, metodo: str, quantas: int | None = None
) -> RunResult:
    """Execução cujas predições do `metodo` perdem as `quantas` primeiras linhas do TESTE.

    Sem `quantas`, perdem todas (o método segue declarado nas predições das outras partições).
    """
    (saida,) = run.saidas
    linhas = pq.read_table(saida.caminho).to_pylist()
    ordenadas = [lin["row_id"] for lin in _do_teste(linhas, metodo)]
    fora = set(ordenadas if quantas is None else ordenadas[:quantas])
    restantes = [
        lin
        for lin in linhas
        if not (lin["metodo"] == metodo and lin["particao"] == "TESTE" and lin["row_id"] in fora)
    ]
    return _regravar(run, destino, restantes)


def predicoes_com_linhas_repetidas(
    run: RunResult, destino: Path, *, metodo: str, quantas: int
) -> RunResult:
    """Execução cujas predições do `metodo` repetem as `quantas` primeiras linhas do TESTE."""
    (saida,) = run.saidas
    linhas = pq.read_table(saida.caminho).to_pylist()
    repetidas = _do_teste(linhas, metodo)[:quantas]
    return _regravar(run, destino, [*linhas, *repetidas])
