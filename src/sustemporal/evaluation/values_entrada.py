"""Conferência completa de cada entrada da P3 antes de qualquer agregação (T13b).

Uma só função confere, nesta ordem: leitura do Parquet, colunas exigidas, tipos físicos contra o
esquema canônico do catálogo, conteúdo (linhas e hash lógico) contra o `DatasetRef` e o domínio de
toda coluna de enum consumida. Qualquer divergência é `FalhaOperacionalErro`, nunca erro cru do
DuckDB nem valor que escorrega para uma categoria.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import duckdb

from sustemporal.contracts import (
    AgregadoRegistro,
    CodigoRotulo,
    EstadoAvaliacao,
    MetodoId,
    ResultadoRegistro,
    RuleEvaluation,
    TipoCanonico,
)
from sustemporal.duck import identificador_seguro
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo

if TYPE_CHECKING:
    from enum import StrEnum

    from sustemporal.contracts import DatasetRef

__all__ = ["EXIGIDAS", "conferir_agregados", "conferir_entrada"]

EXIGIDAS: dict[str, tuple[str, ...]] = {
    "sia_pa_rotulos.v1": (
        "row_id",
        "rotulo",
        "contradicoes",
        "valor_apresentado",
        "valor_aprovado",
    ),
    "agregados_registro.v1": (
        "run_id",
        "row_id",
        "violacoes",
        "conformes",
        "inconclusivas",
        "nao_aplicaveis",
        "resultado",
    ),
    "avaliacoes.v1": ("run_id", "row_id", "rule_id", "versao", "politica_id", "metodo", "estado"),
}
_DOMINIOS: dict[str, dict[str, type[StrEnum]]] = {
    "sia_pa_rotulos.v1": {"rotulo": CodigoRotulo},
    "agregados_registro.v1": {"resultado": ResultadoRegistro},
    "avaliacoes.v1": {"metodo": MetodoId, "estado": EstadoAvaliacao},
}
_FISICO = {
    TipoCanonico.TEXTO: "VARCHAR",
    TipoCanonico.INTEIRO: "BIGINT",
    TipoCanonico.BOOLEANO: "BOOLEAN",
    TipoCanonico.DATA: "DATE",
}


def _compativel(fisico: str, tipo: TipoCanonico) -> bool:
    if tipo is TipoCanonico.DECIMAL:
        return fisico.startswith("DECIMAL(")
    return fisico == _FISICO[tipo]


def _tipos_fisicos(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> dict[str, str]:
    try:
        descricao = con.execute(
            "DESCRIBE SELECT * FROM read_parquet($c)", {"c": dataset.caminho}
        ).fetchall()
    except duckdb.Error as erro:
        raise FalhaOperacionalErro(
            f"valores_entrada_ilegivel_ou_divergente dataset={dataset.dataset_id} erro={erro}"
        ) from erro
    return {str(linha[0]): str(linha[1]) for linha in descricao}


def _exigir_leiaute(dataset: DatasetRef, fisicos: dict[str, str]) -> None:
    exigidas = EXIGIDAS[dataset.schema_id]
    ausentes = [c for c in exigidas if c not in fisicos]
    if ausentes:
        raise FalhaOperacionalErro(
            f"valores_leiaute_incompativel dataset={dataset.dataset_id} "
            f"ausentes={','.join(ausentes)}"
        )
    tipos = {c.nome: c.tipo for c in carregar_esquema(dataset.schema_id).colunas}
    for coluna in exigidas:
        if not _compativel(fisicos[coluna], tipos[coluna]):
            raise FalhaOperacionalErro(
                f"valores_leiaute_incompativel dataset={dataset.dataset_id} coluna={coluna} "
                f"tipo={fisicos[coluna]} esperado={tipos[coluna].value}"
            )


def _exigir_conteudo(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    try:
        verificar_conteudo(con, dataset)
    except (ConteudoDivergente, duckdb.Error, TypeError) as erro:
        raise FalhaOperacionalErro(
            f"valores_entrada_ilegivel_ou_divergente dataset={dataset.dataset_id} erro={erro}"
        ) from erro


def _exigir_dominios(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    dominios = _DOMINIOS[dataset.schema_id]
    for coluna, enum in dominios.items():
        nome = identificador_seguro(coluna, list(dominios))
        fora = con.execute(
            f"SELECT DISTINCT {nome} FROM read_parquet($c) "  # noqa: S608
            f"WHERE {nome} IS NULL OR NOT list_contains($validos, {nome}) ORDER BY 1 LIMIT 1",
            {"c": dataset.caminho, "validos": [membro.value for membro in enum]},
        ).fetchall()
        if fora:
            raise FalhaOperacionalErro(
                f"valores_{coluna}_desconhecido valor={fora[0][0]} dataset={dataset.dataset_id}"
            )


def conferir_entrada(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    """Leitura, colunas exigidas, tipos físicos, conteúdo e domínios de uma entrada da P3.

    Raises:
        FalhaOperacionalErro: Parquet ilegível, coluna ausente, tipo físico incompatível com o
            esquema canônico, conteúdo diferente do `DatasetRef` ou valor fora do domínio.
    """
    fisicos = _tipos_fisicos(con, dataset)
    _exigir_leiaute(dataset, fisicos)
    _exigir_conteudo(con, dataset)
    _exigir_dominios(con, dataset)


_SQL_AVALIACOES = (
    "SELECT row_id, rule_id, estado, metodo, politica_id FROM read_parquet($c) "
    "WHERE run_id = $r ORDER BY row_id, rule_id"
)
_SQL_AGREGADOS = (
    "SELECT row_id, violacoes, conformes, inconclusivas, nao_aplicaveis, resultado "
    "FROM read_parquet($c) WHERE run_id = $r ORDER BY row_id"
)


def _lista(texto: object) -> tuple[str, ...]:
    return tuple(parte for parte in str(texto or "").split(";") if parte)


def _avaliacoes_por_registro(
    con: duckdb.DuckDBPyConnection, avaliacoes: DatasetRef, run_id: str
) -> dict[str, list[RuleEvaluation]]:
    """Só as colunas que `AgregadoRegistro.agregar` lê, já conferidas por `conferir_entrada`."""
    por_registro: dict[str, list[RuleEvaluation]] = {}
    linhas = con.execute(_SQL_AVALIACOES, {"c": avaliacoes.caminho, "r": run_id}).fetchall()
    for row_id, rule_id, estado, metodo, politica_id in linhas:
        campos: dict[str, Any] = {
            "run_id": run_id,
            "row_id": str(row_id),
            "rule_id": str(rule_id),
            "estado": EstadoAvaliacao(str(estado)),
            "metodo": MetodoId(str(metodo)),
            "politica_id": str(politica_id),
        }
        avaliacao = RuleEvaluation.model_construct(**campos)
        por_registro.setdefault(str(row_id), []).append(avaliacao)
    return por_registro


def conferir_agregados(
    con: duckdb.DuckDBPyConnection, agregados: DatasetRef, avaliacoes: DatasetRef, run_id: str
) -> None:
    """Recalcula cada agregado pelas avaliações do registro (`AgregadoRegistro.agregar`).

    Raises:
        FalhaOperacionalErro: agregado diferente do recalculado, avaliação de registro sem
            agregado ou lote de avaliações inválido.
    """
    por_registro = _avaliacoes_por_registro(con, avaliacoes, run_id)
    linhas = con.execute(_SQL_AGREGADOS, {"c": agregados.caminho, "r": run_id}).fetchall()
    for row_id, violacoes, conformes, inconclusivas, nao_aplicaveis, resultado in linhas:
        lido = (
            _lista(violacoes),
            _lista(conformes),
            _lista(inconclusivas),
            _lista(nao_aplicaveis),
            str(resultado),
        )
        try:
            canonico = AgregadoRegistro.agregar(
                run_id, str(row_id), por_registro.pop(str(row_id), [])
            )
        except ValueError as erro:
            raise FalhaOperacionalErro(
                f"valores_agregado_incoerente_com_avaliacoes row={row_id} erro={erro}"
            ) from erro
        esperado = (
            canonico.violacoes,
            canonico.conformes,
            canonico.inconclusivas,
            canonico.nao_aplicaveis,
            canonico.resultado.value,
        )
        if lido != esperado:
            raise FalhaOperacionalErro(f"valores_agregado_incoerente_com_avaliacoes row={row_id}")
    if por_registro:
        raise FalhaOperacionalErro(
            f"valores_agregado_incoerente_com_avaliacoes row={sorted(por_registro)[0]} "
            "motivo=avaliacao_sem_agregado"
        )
