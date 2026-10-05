"""Predições do baseline sem parte das linhas do TESTE, SINTETICO, para a cobertura (T11).

A cópia da execução tem saída própria e consistente com o `DatasetRef` (linhas e hash lógico):
só falta resultado de linhas do TESTE, o que a conferência de conteúdo não pega.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def predicoes_sem_linhas_do_teste(
    run: RunResult, destino: Path, *, metodo: str, quantas: int | None = None
) -> RunResult:
    """Execução cujas predições do `metodo` perdem as `quantas` primeiras linhas do TESTE.

    Sem `quantas`, perdem todas (o método segue declarado nas predições das outras partições).
    """
    (saida,) = run.saidas
    tabela = pq.read_table(saida.caminho)
    linhas = tabela.to_pylist()
    do_teste = [lin for lin in linhas if lin["metodo"] == metodo and lin["particao"] == "TESTE"]
    ordenadas = sorted(lin["row_id"] for lin in do_teste)
    fora = set(ordenadas if quantas is None else ordenadas[:quantas])
    restantes = [
        lin
        for lin in linhas
        if not (lin["metodo"] == metodo and lin["particao"] == "TESTE" and lin["row_id"] in fora)
    ]
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "predicoes.parquet"
    pq.write_table(pa.Table.from_pylist(restantes, schema=tabela.schema), caminho)
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
        linhas=len(restantes),
        artifact_ids=saida.artifact_ids,
        origem_dados=saida.origem_dados,
        produzido_por=saida.produzido_por,
    )
    return run.model_copy(update={"saidas": (nova,)})
