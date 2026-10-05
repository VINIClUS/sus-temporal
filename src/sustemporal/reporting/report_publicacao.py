"""Publicação das tabelas do relatório do piloto: Parquet e `DatasetRef` com hash lógico."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts import DatasetRef
from sustemporal.contracts.records import calcular_dataset_id
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.sia_pa import gravar_parquet, produtor

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import OrigemDados

__all__ = ["TABELAS_RELATORIO", "publicar_tabelas"]

TABELAS_RELATORIO: dict[str, tuple[str, tuple[str, ...]]] = {
    "contagens": ("piloto_contagens.v1", ("dimensao", "valor", "linhas")),
    "exclusoes": ("piloto_exclusoes.v1", ("motivo", "linhas")),
    "campos": ("piloto_campos.v1", ("campo", "ausentes", "denominador")),
    "defasagem": ("piloto_defasagem.v1", ("defasagem_meses", "linhas")),
    "rotulos_resumo": ("piloto_rotulos.v1", ("etapa", "valor", "linhas")),
    "inconclusivos": (
        "piloto_inconclusivos.v1",
        ("rule_id", "fonte", "base", "estado", "classe", "linhas"),
    ),
    "disponibilidade": (
        "piloto_disponibilidade.v1",
        ("familia_regra", "instrumento", "competencia", "base_temporal", "estado", "motivo"),
    ),
}


def publicar_tabelas(
    con: duckdb.DuckDBPyConnection,
    out: Path,
    entradas: Sequence[DatasetRef],
    origem: OrigemDados,
) -> list[DatasetRef]:
    """Grava cada tabela do relatório em `out/<dataset_id>.parquet` (linhagem: as entradas)."""
    artefatos = tuple(sorted({a for entrada in entradas for a in entrada.artifact_ids}))
    publicadas = []
    for tabela, (schema_id, colunas) in TABELAS_RELATORIO.items():
        hash_logico = hash_logico_relacao(con, tabela, colunas)
        dataset_id = calcular_dataset_id(schema_id, hash_logico, artefatos)
        destino = out / f"{dataset_id}.parquet"
        gravar_parquet(con, tabela, destino)
        resultado = con.table(tabela).aggregate("count(*)").fetchone()
        publicadas.append(
            DatasetRef(
                dataset_id=dataset_id,
                schema_id=schema_id,
                caminho=str(destino),
                hash_logico=hash_logico,
                linhas=int(resultado[0]) if resultado else 0,
                artifact_ids=artefatos,
                origem_dados=origem,
                produzido_por=produtor("reporting.report.build_pilot_report"),
            )
        )
    return publicadas
