"""Competência requerida por política e conferência da seleção fornecida (model.md §5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.rules.catalog import requisito_auxiliar
from sustemporal.temporal.selector import criterio_da_regra

if TYPE_CHECKING:
    import duckdb

    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import PoliticaTemporal

__all__ = ["SQL_REQUERIDAS", "SelecaoIncoerente", "conferir_selecoes", "criar_regras_fontes"]

# CTE `requeridas`: por registro e regra, a base do critério da política e a competência
# requerida (nula quando não há critério ou a competência base é nula ou inválida).
SQL_REQUERIDAS = """
pedidos AS (
    SELECT r.row_id, g.rule_id, g.fonte, g.base, g.deslocamento,
        CASE g.base
            WHEN 'ATENDIMENTO' THEN r.competencia_atendimento
            WHEN 'PROCESSAMENTO' THEN r.competencia_processamento
        END AS comp_base
    FROM registros AS r CROSS JOIN regras_fontes AS g
),
requeridas AS (
    SELECT *,
        CASE
            WHEN comp_base IS NULL THEN NULL
            WHEN deslocamento = 0 THEN comp_base
            ELSE strftime(
                try_strptime(comp_base || '01', '%Y%m%d') + to_months(deslocamento), '%Y%m'
            )
        END AS comp
    FROM pedidos
)
"""

_SQL_CONFERIR = f"""
WITH {SQL_REQUERIDAS}
SELECT count(*)
FROM selecoes AS s
JOIN requeridas AS q
    ON q.row_id = s.row_id AND q.rule_id = s.rule_id AND q.fonte = s.fonte
WHERE s.estado <> 'NAO_RESOLVIDA'
    AND (
        q.base IS NULL
        OR q.comp IS NULL
        OR s.base IS DISTINCT FROM q.base
        OR s.competencia_requerida IS DISTINCT FROM q.comp
    )
"""  # noqa: S608


class SelecaoIncoerente(ValueError):
    """Seleção fornecida com base ou competência diferente da política da execução."""


def criar_regras_fontes(
    con: duckdb.DuckDBPyConnection, regras: list[RuleSpec], politica: PoliticaTemporal
) -> None:
    """Cria `regras_fontes`: por regra, a fonte auxiliar e o critério da política para ela.

    O critério vem de `temporal.selector.criterio_da_regra`, a mesma função da seleção em lote:
    em M_TEMP só vale quando coincide com o critério documental da regra (model.md §5).
    """
    pedidos = []
    for regra in regras:
        fonte = requisito_auxiliar(regra).fonte
        criterio = criterio_da_regra(politica, regra, fonte)
        base = str(criterio.base) if criterio else None
        deslocamento = criterio.deslocamento_meses if criterio else 0
        pedidos.append((regra.rule_id, str(fonte), base, deslocamento))
    con.execute(
        "CREATE OR REPLACE TEMP TABLE regras_fontes "
        "(rule_id VARCHAR, fonte VARCHAR, base VARCHAR, deslocamento BIGINT)"
    )
    if pedidos:
        con.executemany("INSERT INTO regras_fontes VALUES (?, ?, ?, ?)", pedidos)


def conferir_selecoes(con: duckdb.DuckDBPyConnection) -> None:
    """Recusa linha de seleção resolvida incoerente com a política (exige `regras_fontes`).

    Raises:
        SelecaoIncoerente: alguma linha com base ou competência requerida divergente.
    """
    incoerentes = con.execute(_SQL_CONFERIR).fetchall()[0][0]
    if incoerentes:
        raise SelecaoIncoerente(f"selecao_incoerente_com_politica linhas={incoerentes}")
