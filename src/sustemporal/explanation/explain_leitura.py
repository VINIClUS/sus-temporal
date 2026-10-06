"""Leitura das saídas imutáveis de uma execução para um registro (nunca de um "latest")."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import duckdb
from pydantic import ValidationError

from sustemporal.contracts.base import MotivoAusencia, ValorNormalizado
from sustemporal.contracts.records import ProductionRecord, RowLocator
from sustemporal.contracts.rules import AgregadoRegistro, MotivoInconclusao, RuleEvaluation
from sustemporal.contracts.temporal import CompetenciaArquivo, SelecaoVersao
from sustemporal.explanation.evidence import ler_evidencia
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo

if TYPE_CHECKING:
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.explanation import Evidence
    from sustemporal.contracts.records import DatasetRef

__all__ = ["ExplicacaoIndisponivel", "SaidasRegistro", "ler_registro", "ler_saidas"]

logger = logging.getLogger(__name__)

_ROW_ID = re.compile(r"^(art_[0-9a-f]{64})(?:/([^#\s]+))?#([0-9]+)$")
_COM_RUN_ID = ("avaliacoes.v1", "selecao_versoes.v1", "agregados_registro.v1", "falhas.v1")
_SAIDAS = ("evidencias.v1", *_COM_RUN_ID)
_CODIGOS = (
    "cnes",
    "municipio_estabelecimento",
    "competencia_atendimento",
    "competencia_processamento",
    "procedimento",
    "cbo",
)


class ExplicacaoIndisponivel(ValueError):
    """Execução, saída ou registro que não permite montar a explicação."""


@dataclass(frozen=True)
class SaidasRegistro:
    avaliacoes: tuple[RuleEvaluation, ...]
    evidencias: tuple[Evidence, ...]
    agregado: AgregadoRegistro
    falhas: tuple[str, ...]


def _lista(texto: object) -> tuple[str, ...]:
    return tuple(parte for parte in str(texto or "").split(";") if parte)


def _saida(run: RunResult, schema_id: str) -> DatasetRef:
    candidatas = [ref for ref in run.saidas if ref.schema_id == schema_id]
    if len(candidatas) != 1:
        raise ExplicacaoIndisponivel(
            f"saida_ausente_ou_repetida run={run.run_id} schema={schema_id} n={len(candidatas)}"
        )
    ref = candidatas[0]
    if ref.produzido_por != run.run_id:
        raise ExplicacaoIndisponivel(
            f"saida_de_outra_execucao run={run.run_id} schema={schema_id} "
            f"produzido_por={ref.produzido_por}"
        )
    return ref


def _conferir(con: duckdb.DuckDBPyConnection, ref: DatasetRef) -> None:
    try:
        verificar_conteudo(con, ref)
    except ConteudoDivergente as erro:
        raise ExplicacaoIndisponivel(str(erro)) from erro
    except (duckdb.Error, OSError) as erro:
        raise ExplicacaoIndisponivel(
            f"saida_ilegivel schema={ref.schema_id} erro={type(erro).__name__}"
        ) from erro


def _linhas(
    con: duckdb.DuckDBPyConnection, consulta: str, parametros: dict[str, object]
) -> list[dict[str, Any]]:
    try:
        cursor = con.execute(consulta, parametros)
        nomes = [coluna[0] for coluna in cursor.description or ()]
        return [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]
    except (duckdb.Error, OSError) as erro:
        raise ExplicacaoIndisponivel(f"saida_ilegivel erro={type(erro).__name__}") from erro


def _exigir_colunas(con: duckdb.DuckDBPyConnection, ref: DatasetRef) -> None:
    """Nomes físicos iguais aos do esquema: o hash lógico não vê coluna fora dele."""
    descricao = _linhas(con, "DESCRIBE SELECT * FROM read_parquet($c)", {"c": ref.caminho})
    fisicas = [str(coluna["column_name"]) for coluna in descricao]
    esperadas = [c.nome for c in carregar_esquema(ref.schema_id).colunas]
    diferencas = {
        "faltam": [nome for nome in esperadas if nome not in fisicas],
        "sobram": [nome for nome in fisicas if nome not in esperadas],
    }
    detalhe = " ".join(f"{chave}={','.join(nomes)}" for chave, nomes in diferencas.items() if nomes)
    if detalhe:
        raise ExplicacaoIndisponivel(
            f"saida_incoerente_com_contrato schema={ref.schema_id} {detalhe}"
        )


def _exigir_mesma_execucao(con: duckdb.DuckDBPyConnection, ref: DatasetRef, run_id: str) -> None:
    alheias = _linhas(
        con,
        "SELECT count(*) AS n FROM read_parquet($c) WHERE run_id IS DISTINCT FROM $r",
        {"c": ref.caminho, "r": run_id},
    )[0]["n"]
    if alheias:
        raise ExplicacaoIndisponivel(
            f"saida_mistura_execucoes run={run_id} schema={ref.schema_id} linhas={alheias}"
        )


def _selecao(linha: dict[str, Any]) -> SelecaoVersao:
    competencia = linha["competencia_requerida"]
    return SelecaoVersao(
        fonte=linha["fonte"],
        base=linha["base"],
        competencia_requerida=CompetenciaArquivo(competencia) if competencia else None,
        estado=linha["estado"],
        artifact_ids=_lista(linha["artifact_ids"]),
        observation_ids=_lista(linha["observation_ids"]),
        motivo=linha["motivo"] or "",
    )


def _avaliacao(linha: dict[str, Any], selecoes: list[dict[str, Any]]) -> RuleEvaluation:
    proprias = [_selecao(s) for s in selecoes if s["rule_id"] == linha["rule_id"]]
    return RuleEvaluation(
        **{c: linha[c] for c in ("run_id", "row_id", "rule_id", "versao", "politica_id")},
        metodo=linha["metodo"],
        estado=linha["estado"],
        aplicabilidade=linha["aplicabilidade"],
        insumos_completos=linha["insumos_completos"],
        incompatibilidade_demonstrada=linha["incompatibilidade_demonstrada"],
        motivos=tuple(MotivoInconclusao(m) for m in _lista(linha["motivos"])),
        selecoes=tuple(sorted(proprias, key=lambda s: s.fonte)),
        evidence_ids=_lista(linha["evidence_ids"]),
    )


def _agregado(linhas: list[dict[str, Any]], row_id: str) -> AgregadoRegistro:
    if len(linhas) != 1:
        raise ExplicacaoIndisponivel(f"registro_sem_agregado row={row_id} n={len(linhas)}")
    linha = linhas[0]
    return AgregadoRegistro(
        run_id=linha["run_id"],
        row_id=linha["row_id"],
        violacoes=_lista(linha["violacoes"]),
        conformes=_lista(linha["conformes"]),
        inconclusivas=_lista(linha["inconclusivas"]),
        nao_aplicaveis=_lista(linha["nao_aplicaveis"]),
        resultado=linha["resultado"],
    )


def _ler(
    con: duckdb.DuckDBPyConnection, refs: dict[str, DatasetRef], row_id: str
) -> dict[str, list[dict[str, Any]]]:
    por_registro = {}
    for schema_id in _COM_RUN_ID:
        filtro = "row_id = $row OR row_id IS NULL" if schema_id == "falhas.v1" else "row_id = $row"
        por_registro[schema_id] = _linhas(
            con,
            f"SELECT * FROM read_parquet($c) WHERE {filtro}",  # noqa: S608
            {"c": refs[schema_id].caminho, "row": row_id},
        )
    citadas = sorted({e for a in por_registro["avaliacoes.v1"] for e in _lista(a["evidence_ids"])})
    por_registro["evidencias.v1"] = _linhas(
        con,
        "SELECT * FROM read_parquet($c) WHERE list_contains($ids, evidence_id) "
        "ORDER BY evidence_id",
        {"c": refs["evidencias.v1"].caminho, "ids": citadas},
    )
    return por_registro


def _montar(linhas: dict[str, list[dict[str, Any]]], run: RunResult, row_id: str) -> SaidasRegistro:
    """Valida cada linha antes de ordenar: chave nula é recusa, nunca TypeError."""
    lidas = [_avaliacao(linha, linhas["selecao_versoes.v1"]) for linha in linhas["avaliacoes.v1"]]
    avaliacoes = tuple(sorted(lidas, key=lambda a: a.rule_id))
    agregado = _agregado(linhas["agregados_registro.v1"], row_id)
    if agregado != AgregadoRegistro.agregar(run.run_id, row_id, avaliacoes):
        raise ExplicacaoIndisponivel(f"agregado_divergente run={run.run_id} row={row_id}")
    return SaidasRegistro(
        avaliacoes=avaliacoes,
        evidencias=tuple(ler_evidencia(linha) for linha in linhas["evidencias.v1"]),
        agregado=agregado,
        falhas=tuple(str(f["erro"]) for f in linhas["falhas.v1"]),
    )


def ler_saidas(con: duckdb.DuckDBPyConnection, run: RunResult, row_id: str) -> SaidasRegistro:
    """Avaliações, seleções, evidências e agregado do registro, conferidos contra os DatasetRef.

    Raises:
        ExplicacaoIndisponivel: saída ausente, alheia, divergente, fora do esquema (coluna
            ausente ou valor fora do contrato), ou registro sem avaliação.
    """
    refs = {schema_id: _saida(run, schema_id) for schema_id in _SAIDAS}
    for ref in refs.values():
        _conferir(con, ref)
        _exigir_colunas(con, ref)
    for schema_id in _COM_RUN_ID:
        _exigir_mesma_execucao(con, refs[schema_id], run.run_id)
    linhas = _ler(con, refs, row_id)
    if not linhas["avaliacoes.v1"]:
        raise ExplicacaoIndisponivel(f"registro_sem_avaliacao run={run.run_id} row={row_id}")
    if linhas["falhas.v1"]:
        etapas = sorted({str(f["etapa"]) for f in linhas["falhas.v1"]})
        raise ExplicacaoIndisponivel(
            f"registro_com_falha_operacional run={run.run_id} row={row_id} etapas={etapas}"
        )
    try:
        saidas = _montar(linhas, run, row_id)
    except (ValidationError, ValueError) as erro:
        if isinstance(erro, ExplicacaoIndisponivel):
            raise
        raise ExplicacaoIndisponivel(f"saida_incoerente_com_contrato row={row_id}") from erro
    logger.info(
        "saidas_lidas run=%s row=%s avaliacoes=%d", run.run_id, row_id, len(saidas.avaliacoes)
    )
    return saidas


def _valor(linha: dict[str, Any], nome: str) -> str | None:
    valor = linha.get(nome)
    return None if valor is None else str(valor)


def _instrumento(linha: dict[str, Any]) -> ValorNormalizado:
    valor = _valor(linha, "instrumento")
    bruto = _valor(linha, "instrumento_bruto")
    if valor is not None:
        return ValorNormalizado(bruto=bruto if bruto is not None else valor, valor=valor)
    motivo = _valor(linha, "instrumento_motivo") or MotivoAusencia.DESCONHECIDO
    return ValorNormalizado(bruto=bruto, valor=None, motivo=MotivoAusencia(motivo))


def ler_registro(con: duckdb.DuckDBPyConnection, run: RunResult, row_id: str) -> ProductionRecord:
    """Registro SIA-PA avaliado, lido do conjunto de entrada conferido da execução.

    Raises:
        ExplicacaoIndisponivel: conjunto ausente ou divergente, ou registro inexistente.
    """
    encontrado = _ROW_ID.fullmatch(row_id)
    entradas = [d for d in run.entradas if d.schema_id == "sia_pa.v1"]
    if encontrado is None or len(entradas) != 1:
        raise ExplicacaoIndisponivel(f"registro_indisponivel run={run.run_id} row={row_id}")
    artifact_id, membro, indice = encontrado.groups()
    if artifact_id not in entradas[0].artifact_ids:
        raise ExplicacaoIndisponivel(
            f"registro_fora_do_conjunto row={row_id} dataset_id={entradas[0].dataset_id}"
        )
    _conferir(con, entradas[0])
    linhas = _linhas(
        con,
        "SELECT * FROM read_parquet($c) WHERE row_id = $row",
        {"c": entradas[0].caminho, "row": row_id},
    )
    if len(linhas) != 1:
        raise ExplicacaoIndisponivel(f"registro_inexistente_na_entrada row={row_id}")
    linha = linhas[0]
    try:
        origem = RowLocator(
            artifact_id=artifact_id,
            membro=membro,
            indice=int(indice),
            deletado=bool(linha.get("deletado") or False),
        )
        return ProductionRecord.model_validate(
            {nome: _valor(linha, nome) for nome in _CODIGOS}
            | {"row_id": row_id, "origem": origem, "instrumento": _instrumento(linha)}
        )
    except (ValidationError, ValueError) as erro:
        raise ExplicacaoIndisponivel(f"registro_incoerente_com_contrato row={row_id}") from erro
