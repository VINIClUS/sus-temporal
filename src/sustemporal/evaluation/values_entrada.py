"""Conferência completa de cada entrada da P3 antes de qualquer agregação (T13b).

Uma só função confere, nesta ordem: leitura do Parquet, colunas exigidas, tipos físicos contra o
esquema canônico do catálogo, conteúdo (linhas e hash lógico) contra o `DatasetRef` e o domínio de
toda coluna de enum consumida. Qualquer divergência é `FalhaOperacionalErro`, nunca erro cru do
DuckDB nem valor que escorrega para uma categoria.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import duckdb
from pydantic import ValidationError

from sustemporal.contracts import (
    AgregadoRegistro,
    Aplicabilidade,
    BaseTemporal,
    CodigoRotulo,
    EstadoAvaliacao,
    EstadoSelecao,
    FamiliaFonte,
    MetodoId,
    ResultadoRegistro,
    RuleEvaluation,
    SelecaoVersao,
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
    "avaliacoes.v1": (
        "run_id",
        "row_id",
        "rule_id",
        "versao",
        "politica_id",
        "metodo",
        "estado",
        "aplicabilidade",
        "insumos_completos",
        "incompatibilidade_demonstrada",
        "motivos",
        "evidence_ids",
    ),
    "selecao_versoes.v1": (
        "run_id",
        "row_id",
        "rule_id",
        "fonte",
        "base",
        "competencia_requerida",
        "estado",
        "artifact_ids",
        "observation_ids",
        "motivo",
    ),
}
_DOMINIOS: dict[str, dict[str, type[StrEnum]]] = {
    "sia_pa_rotulos.v1": {"rotulo": CodigoRotulo},
    "agregados_registro.v1": {"resultado": ResultadoRegistro},
    "avaliacoes.v1": {
        "metodo": MetodoId,
        "estado": EstadoAvaliacao,
        "aplicabilidade": Aplicabilidade,
    },
    "selecao_versoes.v1": {
        "fonte": FamiliaFonte,
        "base": BaseTemporal,
        "estado": EstadoSelecao,
    },
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


def _exigir_nulabilidade(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    exigidas = EXIGIDAS[dataset.schema_id]
    nao_anulaveis = [
        c.nome
        for c in carregar_esquema(dataset.schema_id).colunas
        if c.nome in exigidas and not c.anulavel
    ]
    for coluna in nao_anulaveis:
        nome = identificador_seguro(coluna, nao_anulaveis)
        nulos = con.execute(
            f"SELECT count(*) FROM read_parquet($c) WHERE {nome} IS NULL",  # noqa: S608
            {"c": dataset.caminho},
        ).fetchall()[0][0]
        if nulos:
            raise FalhaOperacionalErro(
                f"valores_nulo_em_coluna_nao_anulavel dataset={dataset.dataset_id} "
                f"coluna={coluna} nulos={nulos}"
            )


def _exigir_dominios(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    dominios = _DOMINIOS[dataset.schema_id]
    for coluna, enum in dominios.items():
        nome = identificador_seguro(coluna, list(dominios))
        fora = con.execute(
            f"SELECT DISTINCT {nome} FROM read_parquet($c) "  # noqa: S608
            f"WHERE {nome} IS NOT NULL AND NOT list_contains($validos, {nome}) "
            "ORDER BY 1 LIMIT 1",
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
            esquema canônico, conteúdo diferente do `DatasetRef`, nulo em coluna não anulável
            ou valor fora do domínio.
    """
    fisicos = _tipos_fisicos(con, dataset)
    _exigir_leiaute(dataset, fisicos)
    _exigir_conteudo(con, dataset)
    _exigir_nulabilidade(con, dataset)
    _exigir_dominios(con, dataset)


def _lista(texto: object) -> tuple[str, ...]:
    return tuple(parte for parte in str(texto or "").split(";") if parte)


def _linhas(
    con: duckdb.DuckDBPyConnection, dataset: DatasetRef, run_id: str
) -> list[dict[str, Any]]:
    colunas = EXIGIDAS[dataset.schema_id]
    projecao = ", ".join(identificador_seguro(c, colunas) for c in colunas)
    cursor = con.execute(
        f"SELECT {projecao} FROM read_parquet($c) WHERE run_id = $r "  # noqa: S608
        "ORDER BY row_id",
        {"c": dataset.caminho, "r": run_id},
    )
    return [dict(zip(colunas, linha, strict=True)) for linha in cursor.fetchall()]


def _selecao(linha: dict[str, Any]) -> SelecaoVersao:
    return SelecaoVersao.model_validate(
        {
            "fonte": linha["fonte"],
            "base": linha["base"],
            "competencia_requerida": linha["competencia_requerida"] or None,
            "estado": linha["estado"],
            "artifact_ids": _lista(linha["artifact_ids"]),
            "observation_ids": _lista(linha["observation_ids"]),
            "motivo": linha["motivo"] or "",
        }
    )


def _avaliacao(linha: dict[str, Any], selecoes: list[SelecaoVersao]) -> RuleEvaluation:
    return RuleEvaluation.model_validate(
        {
            **{c: linha[c] for c in ("run_id", "row_id", "rule_id", "versao", "politica_id")},
            "metodo": linha["metodo"],
            "estado": linha["estado"],
            "aplicabilidade": linha["aplicabilidade"],
            "insumos_completos": linha["insumos_completos"],
            "incompatibilidade_demonstrada": linha["incompatibilidade_demonstrada"],
            "motivos": _lista(linha["motivos"]),
            "selecoes": tuple(sorted(selecoes, key=lambda s: s.fonte)),
            "evidence_ids": _lista(linha["evidence_ids"]),
        }
    )


def _avaliacoes_validadas(
    con: duckdb.DuckDBPyConnection, avaliacoes: DatasetRef, selecoes: DatasetRef, run_id: str
) -> dict[str, list[RuleEvaluation]]:
    """Cada linha de avaliação validada pelo contrato `RuleEvaluation`, com suas seleções."""
    por_regra: dict[tuple[str, str], list[SelecaoVersao]] = {}
    for linha in _linhas(con, selecoes, run_id):
        chave = (str(linha["row_id"]), str(linha["rule_id"]))
        try:
            por_regra.setdefault(chave, []).append(_selecao(linha))
        except ValidationError as erro:
            raise FalhaOperacionalErro(
                f"valores_selecao_incoerente row={chave[0]} regra={chave[1]}"
            ) from erro
    por_registro: dict[str, list[RuleEvaluation]] = {}
    for linha in _linhas(con, avaliacoes, run_id):
        chave = (str(linha["row_id"]), str(linha["rule_id"]))
        try:
            avaliacao = _avaliacao(linha, por_regra.get(chave, []))
        except ValidationError as erro:
            raise FalhaOperacionalErro(
                f"valores_avaliacao_incoerente row={chave[0]} regra={chave[1]}"
            ) from erro
        por_registro.setdefault(chave[0], []).append(avaliacao)
    return por_registro


def _agregado(linha: dict[str, Any]) -> AgregadoRegistro:
    try:
        return AgregadoRegistro.model_validate(
            {
                "run_id": linha["run_id"],
                "row_id": linha["row_id"],
                "violacoes": _lista(linha["violacoes"]),
                "conformes": _lista(linha["conformes"]),
                "inconclusivas": _lista(linha["inconclusivas"]),
                "nao_aplicaveis": _lista(linha["nao_aplicaveis"]),
                "resultado": linha["resultado"],
            }
        )
    except ValidationError as erro:
        raise FalhaOperacionalErro(
            f"valores_agregado_incoerente_com_avaliacoes row={linha['row_id']} "
            "motivo=agregado_invalido"
        ) from erro


def conferir_agregados(
    con: duckdb.DuckDBPyConnection,
    agregados: DatasetRef,
    avaliacoes: DatasetRef,
    selecoes: DatasetRef,
    *,
    run_id: str,
) -> None:
    """Valida avaliações e agregados pelos contratos e recalcula cada agregado das avaliações.

    Raises:
        FalhaOperacionalErro: seleção, avaliação ou agregado incoerente com o contrato, agregado
            diferente do recalculado por `AgregadoRegistro.agregar` ou avaliação sem agregado.
    """
    por_registro = _avaliacoes_validadas(con, avaliacoes, selecoes, run_id)
    for linha in _linhas(con, agregados, run_id):
        lido = _agregado(linha)
        try:
            canonico = AgregadoRegistro.agregar(
                run_id, lido.row_id, por_registro.pop(lido.row_id, [])
            )
        except ValueError as erro:
            raise FalhaOperacionalErro(
                f"valores_agregado_incoerente_com_avaliacoes row={lido.row_id} erro={erro}"
            ) from erro
        if lido != canonico:
            raise FalhaOperacionalErro(
                f"valores_agregado_incoerente_com_avaliacoes row={lido.row_id}"
            )
    if por_registro:
        raise FalhaOperacionalErro(
            f"valores_agregado_incoerente_com_avaliacoes row={sorted(por_registro)[0]} "
            "motivo=avaliacao_sem_agregado"
        )
