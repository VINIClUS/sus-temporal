"""Seleção de versões sintética (SINTETICO) do relatório do piloto: AUSENTE citando observações."""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts import OrigemDados
from sustemporal.temporal.lote import gravar_selecoes

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef

__all__ = ["selecao_sintetica"]


def selecao_sintetica(pasta: Path, sia_pa: DatasetRef, *, observation_ids: str) -> DatasetRef:
    """`selecao_versoes.v1` com uma linha AUSENTE por registro do `sia_pa`, citando as observações.

    `observation_ids` é o texto do campo (ids unidos por `;`; vazio quando nenhuma tentativa).
    """
    destino = pasta / "selecao"
    with closing(duckdb.connect()) as con:
        con.execute(
            "CREATE TABLE selecao_versoes AS SELECT 'run_sintetico' AS run_id, row_id, "
            "'R_SINTETICA' AS rule_id, 'SIGTAP' AS fonte, 'PROCESSAMENTO' AS base, "
            "'201801' AS competencia_requerida, 'AUSENTE' AS estado, '' AS artifact_ids, "
            "$citadas AS observation_ids, 'sem_conteudo_obtido' AS motivo "
            "FROM read_parquet($caminho)",
            {"citadas": observation_ids, "caminho": sia_pa.caminho},
        )
        return gravar_selecoes(con, destino, run_id="sintetico", origem=OrigemDados.SINTETICO)
