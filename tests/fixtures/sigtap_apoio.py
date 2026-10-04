"""Apoio aos testes do SIGTAP: normalização de zips sintéticos (SINTETICO) e leitura do Parquet."""

from __future__ import annotations

import functools
from contextlib import closing
from typing import TYPE_CHECKING, Any

import duckdb
import pytest

from sustemporal.contracts import LayoutSpec, OrigemDados, RuntimeConfig
from sustemporal.ingest.dbf import QuarentenaLeitura
from sustemporal.ingest.sigtap import normalize_sigtap
from sustemporal.ingest.sigtap_zip import carregar_leiautes_sigtap
from tests.fixtures.sigtap_zip import artefato_sigtap, zip_sigtap

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, DatasetRef

__all__ = ["leiautes", "ler_linhas", "normalizar", "pacote", "quarentena", "runtime"]


@functools.cache
def leiautes() -> dict[str, LayoutSpec]:
    return carregar_leiautes_sigtap()


def runtime(pasta: Path) -> RuntimeConfig:
    return RuntimeConfig(raiz_dados=str(pasta), duckdb_memoria="256MB", duckdb_threads=1)


def normalizar(
    pasta: Path,
    artefato: ArtifactVersion,
    tabela: str,
    *,
    layout: LayoutSpec | None = None,
    limite_membro_bytes: int | None = None,
) -> DatasetRef:
    saida = pasta / "saida"
    saida.mkdir(parents=True, exist_ok=True)
    extras = {} if limite_membro_bytes is None else {"limite_membro_bytes": limite_membro_bytes}
    return normalize_sigtap(
        artefato,
        layout or leiautes()[tabela],
        saida,
        runtime=runtime(pasta),
        origem_dados=OrigemDados.SINTETICO,
        **extras,
    )


def pacote(
    pasta: Path,
    membros: dict[str, bytes],
    *,
    geracao: str = "1801101010",
    competencia: str | None = "201801",
) -> ArtifactVersion:
    return artefato_sigtap(pasta, zip_sigtap(membros), geracao=geracao, competencia=competencia)


def ler_linhas(dataset: DatasetRef) -> list[dict[str, Any]]:
    with closing(duckdb.connect()) as con:
        relacao = con.execute("SELECT * FROM read_parquet($c)", {"c": dataset.caminho})
        nomes = [d[0] for d in relacao.description]
        return [dict(zip(nomes, linha, strict=True)) for linha in relacao.fetchall()]


def quarentena(pasta: Path, membros: dict[str, bytes], tabela: str) -> QuarentenaLeitura:
    artefato = pacote(pasta, membros)
    with pytest.raises(QuarentenaLeitura) as erro:
        normalizar(pasta, artefato, tabela)
    return erro.value
