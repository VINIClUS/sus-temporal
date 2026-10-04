"""Rótulos recortados pelas mesmas partições da população (T10)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.sia_pa import gravar_parquet, produtor
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.experiment import Particao

__all__ = ["SCHEMA_ROTULOS", "particionar_rotulos"]

logger = logging.getLogger(__name__)

SCHEMA_ROTULOS = "sia_pa_rotulos.v1"


def _verificar(con: duckdb.DuckDBPyConnection, rotulos: DatasetRef) -> None:
    if rotulos.schema_id != SCHEMA_ROTULOS:
        raise ValueError(f"split_rotulos_schema_invalido schema={rotulos.schema_id}")
    try:
        verificar_conteudo(con, rotulos)
    except (ConteudoDivergente, duckdb.Error) as erro:
        raise FalhaOperacionalErro(
            f"split_rotulos_ilegiveis_ou_divergentes dataset={rotulos.dataset_id} erro={erro}"
        ) from erro


def _recortar(
    con: duckdb.DuckDBPyConnection, rotulos: DatasetRef, populacao: DatasetRef, out: Path
) -> DatasetRef:
    colunas = [c.nome for c in carregar_esquema(SCHEMA_ROTULOS).colunas]
    projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE rotulos_particao AS SELECT {projecao} "  # noqa: S608
        "FROM read_parquet($r) WHERE row_id IN (SELECT row_id FROM read_parquet($p)) "
        "ORDER BY row_id",
        {"r": rotulos.caminho, "p": populacao.caminho},
    )
    hash_logico = hash_logico_relacao(con, "rotulos_particao", colunas)
    linhas = int(con.execute("SELECT count(*) FROM rotulos_particao").fetchall()[0][0])
    dataset_id = calcular_dataset_id(SCHEMA_ROTULOS, hash_logico, populacao.artifact_ids)
    destino = out / f"{dataset_id}.parquet"
    gravar_parquet(con, "rotulos_particao", destino)
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=SCHEMA_ROTULOS,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=populacao.artifact_ids,
        origem_dados=rotulos.origem_dados,
        produzido_por=produtor("evaluation.split.build_splits"),
    )


def particionar_rotulos(
    rotulos: DatasetRef, particoes: dict[Particao, DatasetRef], out: Path
) -> dict[Particao, DatasetRef]:
    """Rótulos só dos registros de cada partição, com hash próprio.

    Assim etapas anteriores ao G2 citam e conferem só os rótulos das partições permitidas.

    Raises:
        FalhaOperacionalErro: rótulos ilegíveis ou diferentes do `DatasetRef`.
        ValueError: esquema inesperado ou origem diferente da população.
    """
    if any(ds.origem_dados is not rotulos.origem_dados for ds in particoes.values()):
        raise ValueError(f"split_rotulos_de_outra_origem dataset={rotulos.dataset_id}")
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        _verificar(con, rotulos)
        recortes = {p: _recortar(con, rotulos, ds, out) for p, ds in particoes.items()}
    finally:
        con.close()
    logger.info(
        "rotulos_particionados dataset=%s linhas=%s",
        rotulos.dataset_id,
        {p.value: ds.linhas for p, ds in recortes.items()},
    )
    return recortes
