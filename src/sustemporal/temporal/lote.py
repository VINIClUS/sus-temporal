"""Seleção em lote no DuckDB, equivalente à seleção por registro (`selecao_versoes.v1`).

O DuckDB calcula, por registro, regra e fonte, a competência requerida pela política. A decisão
para cada chave distinta (fonte, base, competência requerida) é a mesma `selecionar_versao` da
seleção por registro, então as duas coincidem por construção (e por teste de propriedade).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.temporal import CompetenciaArquivo
from sustemporal.duck import identificador_seguro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.temporal.selector import (
    criterio_ou_motivo,
    fontes_auxiliares,
    selecionar_versao,
)
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from datetime import datetime

    import duckdb

    from sustemporal.contracts.base import OrigemDados
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import PoliticaTemporal
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = [
    "ESQUEMA",
    "SCHEMA_ID",
    "TABELA",
    "colunas_do_esquema",
    "gravar_selecoes",
    "selecionar_lote",
]

logger = logging.getLogger(__name__)

TABELA = "selecao_versoes"
SCHEMA_ID = "selecao_versoes.v1"
ESQUEMA = Path("catalog/schemas/selecao_versoes.yaml")

_SQL_PEDIDOS = """
CREATE OR REPLACE TEMP TABLE _pedidos AS
WITH base AS (
    SELECT r.row_id, g.rule_id, g.fonte, g.base, g.deslocamento, g.motivo_politica,
        CASE g.base
            WHEN 'ATENDIMENTO' THEN r.competencia_atendimento
            WHEN 'PROCESSAMENTO' THEN r.competencia_processamento
        END AS comp_base
    FROM {registros} AS r CROSS JOIN _regras_fontes AS g
)
SELECT *,
    CASE
        WHEN comp_base IS NULL THEN NULL
        WHEN deslocamento = 0 THEN comp_base
        ELSE strftime(strptime(comp_base || '01', '%Y%m%d') + to_months(deslocamento), '%Y%m')
    END AS requerida
FROM base
"""

_SQL_SELECAO = """
CREATE OR REPLACE TABLE selecao_versoes AS
SELECT
    CAST($run_id AS VARCHAR) AS run_id,
    p.row_id,
    p.rule_id,
    p.fonte,
    CASE WHEN p.motivo_politica IS NULL AND p.requerida IS NOT NULL THEN p.base END AS base,
    CASE WHEN p.motivo_politica IS NULL THEN p.requerida END AS competencia_requerida,
    COALESCE(s.estado, 'NAO_RESOLVIDA') AS estado,
    COALESCE(s.artifact_ids, '') AS artifact_ids,
    COALESCE(s.observation_ids, '') AS observation_ids,
    CASE
        WHEN p.motivo_politica IS NOT NULL THEN p.motivo_politica
        WHEN p.requerida IS NULL THEN 'competencia_base_ausente base=' || p.base
        ELSE s.motivo
    END AS motivo
FROM _pedidos AS p
LEFT JOIN _selecoes_chave AS s
    ON p.motivo_politica IS NULL
    AND s.fonte = p.fonte AND s.base = p.base AND s.requerida = p.requerida
"""


def _regras_fontes(
    regras: list[RuleSpec], politica: PoliticaTemporal
) -> list[tuple[str, str, str | None, int, str | None]]:
    linhas: list[tuple[str, str, str | None, int, str | None]] = []
    for regra in regras:
        for fonte in fontes_auxiliares(regra):
            criterio = criterio_ou_motivo(politica, fonte)
            if isinstance(criterio, str):
                linhas.append((regra.rule_id, fonte.value, None, 0, criterio))
            else:
                base = criterio.base.value
                linhas.append((regra.rule_id, fonte.value, base, criterio.deslocamento_meses, None))
    return linhas


def _criar_pedidos(
    con: duckdb.DuckDBPyConnection, registros: str, linhas: list[tuple[object, ...]]
) -> None:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _regras_fontes (rule_id VARCHAR, fonte VARCHAR, "
        "base VARCHAR, deslocamento BIGINT, motivo_politica VARCHAR)"
    )
    if linhas:
        con.executemany("INSERT INTO _regras_fontes VALUES (?, ?, ?, ?, ?)", linhas)
    tabelas = {str(t[0]) for t in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    citada = identificador_seguro(registros, tabelas)
    con.execute(_SQL_PEDIDOS.format(registros=citada))


def _decidir_chaves(
    con: duckdb.DuckDBPyConnection,
    politica: PoliticaTemporal,
    registro: RegistroTemporal,
    contexto: tuple[str | None, datetime | None],
) -> None:
    uf, corte = contexto
    chaves = con.execute(
        "SELECT DISTINCT fonte, base, requerida FROM _pedidos "
        "WHERE motivo_politica IS NULL AND requerida IS NOT NULL ORDER BY 1, 2, 3"
    ).fetchall()
    criterios = {c.fonte.value: c for c in politica.criterios}
    decisoes = []
    for fonte, base, requerida in chaves:
        selecao = selecionar_versao(
            registro, criterios[fonte], CompetenciaArquivo(requerida), uf=uf, corte=corte
        )
        artefatos, observacoes = ";".join(selecao.artifact_ids), ";".join(selecao.observation_ids)
        estado = selecao.estado.value
        decisoes.append((fonte, base, requerida, estado, artefatos, observacoes, selecao.motivo))
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _selecoes_chave (fonte VARCHAR, base VARCHAR, "
        "requerida VARCHAR, estado VARCHAR, artifact_ids VARCHAR, observation_ids VARCHAR, "
        "motivo VARCHAR)"
    )
    if decisoes:
        con.executemany("INSERT INTO _selecoes_chave VALUES (?, ?, ?, ?, ?, ?, ?)", decisoes)


def selecionar_lote(
    con: duckdb.DuckDBPyConnection,
    registros: str,
    regras: list[RuleSpec],
    politica: PoliticaTemporal,
    registro: RegistroTemporal,
    *,
    run_id: str,
    uf: str | None = None,
    corte: datetime | None = None,
) -> None:
    """Cria `selecao_versoes` a partir da tabela `registros` (row_id e as duas competências).

    `registros` precisa ter `row_id`, `competencia_atendimento` e `competencia_processamento`
    (VARCHAR AAAAMM ou nulo).

    Raises:
        ValueError: nome de tabela fora do catálogo do DuckDB.
    """
    _criar_pedidos(con, registros, list(_regras_fontes(regras, politica)))
    _decidir_chaves(con, politica, registro, (uf, corte))
    con.execute(_SQL_SELECAO, {"run_id": run_id})
    total = con.execute("SELECT count(*) FROM selecao_versoes").fetchall()[0][0]
    logger.info("selecao_lote_concluida run_id=%s linhas=%d", run_id, total)


def colunas_do_esquema(esquema: Path = ESQUEMA) -> list[str]:
    conteudo = carregar_yaml(esquema)
    return [str(coluna["nome"]) for coluna in conteudo["colunas"]]


def gravar_selecoes(
    con: duckdb.DuckDBPyConnection, destino: Path, *, run_id: str, origem: OrigemDados
) -> DatasetRef:
    """Grava `selecao_versoes` em Parquet e devolve o `DatasetRef` (hash lógico sobre o esquema)."""
    colunas = colunas_do_esquema()
    lista = ", ".join(identificador_seguro(c, colunas) for c in colunas)
    destino.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"SELECT {lista} FROM selecao_versoes").write_parquet(str(destino))  # noqa: S608
    hash_logico = hash_logico_relacao(con, TABELA, colunas)
    linhas = int(con.execute("SELECT count(*) FROM selecao_versoes").fetchall()[0][0])
    artefatos = con.execute(
        "SELECT DISTINCT a FROM (SELECT unnest(string_split(artifact_ids, ';')) AS a "
        "FROM selecao_versoes) WHERE a <> '' ORDER BY a"
    ).fetchall()
    ids = tuple(str(linha[0]) for linha in artefatos)
    return DatasetRef(
        dataset_id=calcular_dataset_id(SCHEMA_ID, hash_logico, ids),
        schema_id=SCHEMA_ID,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=ids,
        origem_dados=origem,
        produzido_por=run_id,
    )
