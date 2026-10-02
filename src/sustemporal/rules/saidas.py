"""Validação contra os contratos e gravação das saídas da avaliação com hash lógico."""

from __future__ import annotations

import itertools
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sustemporal.contracts.explanation import Evidence
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.rules import AgregadoRegistro, MotivoInconclusao, RuleEvaluation
from sustemporal.contracts.temporal import CompetenciaArquivo, SelecaoVersao
from sustemporal.hashing import hash_logico_relacao

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import duckdb

    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import PoliticaTemporal
    from sustemporal.rules.falhas import RegistroFalhas
    from sustemporal.rules.insumos import InsumosAvaliacao

__all__ = [
    "COLUNAS_AGREGADOS",
    "COLUNAS_AVALIACOES",
    "COLUNAS_BRUTAS",
    "COLUNAS_EVIDENCIAS",
    "COLUNAS_FALHAS",
    "COLUNAS_SELECOES",
    "ContextoSaida",
    "gravar_saidas",
]

logger = logging.getLogger(__name__)

_TEXTO = "VARCHAR"
COLUNAS_BRUTAS: tuple[tuple[str, str], ...] = (
    ("row_id", _TEXTO),
    ("rule_id", _TEXTO),
    ("estado", _TEXTO),
    ("aplicabilidade", _TEXTO),
    ("insumos_completos", "BOOLEAN"),
    ("incompatibilidade_demonstrada", "BOOLEAN"),
    ("motivos", _TEXTO),
    ("sel_fonte", _TEXTO),
    ("sel_base", _TEXTO),
    ("sel_competencia", _TEXTO),
    ("sel_estado", _TEXTO),
    ("sel_artefatos", _TEXTO),
    ("sel_observacoes", _TEXTO),
    ("sel_motivo", _TEXTO),
    ("ev_id", _TEXTO),
    ("ev_tipo", _TEXTO),
    ("ev_query_id", _TEXTO),
    ("ev_sql_sha256", _TEXTO),
    ("ev_parametros", _TEXTO),
    ("ev_dataset_id", _TEXTO),
    ("ev_hash_logico", _TEXTO),
    ("ev_artifact_ids", _TEXTO),
    ("ev_cobertura", _TEXTO),
    ("ev_integridade", _TEXTO),
    ("ev_n_resultados", "BIGINT"),
    ("ev_chaves_amostra", _TEXTO),
)
COLUNAS_AVALIACOES = (
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
)
COLUNAS_EVIDENCIAS = (
    "evidence_id",
    "tipo",
    "query_id",
    "sql_sha256",
    "parametros",
    "dataset_id",
    "hash_logico",
    "artifact_ids",
    "cobertura",
    "integridade",
    "n_resultados",
    "chaves_amostra",
)
COLUNAS_AGREGADOS = (
    "run_id",
    "row_id",
    "violacoes",
    "conformes",
    "inconclusivas",
    "nao_aplicaveis",
    "resultado",
)
COLUNAS_SELECOES = (
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
)
COLUNAS_FALHAS = ("run_id", "sequencia", "etapa", "row_id", "rule_id", "erro", "ocorrida_em")
_LOTE = 10_000
_INDICE = {nome: posicao for posicao, (nome, _tipo) in enumerate(COLUNAS_BRUTAS)}


@dataclass(frozen=True)
class ContextoSaida:
    """Estado imutável de uma execução de validação."""

    run_id: str
    dataset: DatasetRef
    regras: list[RuleSpec]
    politica: PoliticaTemporal
    insumos: InsumosAvaliacao
    destino: Path
    falhas: RegistroFalhas


def _lista(texto: object) -> tuple[str, ...]:
    return tuple(parte for parte in str(texto or "").split(";") if parte)


def _selecoes(linha: tuple[Any, ...]) -> tuple[SelecaoVersao, ...]:
    if linha[_INDICE["sel_estado"]] is None:
        return ()
    competencia = linha[_INDICE["sel_competencia"]]
    return (
        SelecaoVersao(
            fonte=linha[_INDICE["sel_fonte"]],
            base=linha[_INDICE["sel_base"]],
            competencia_requerida=CompetenciaArquivo(competencia) if competencia else None,
            estado=linha[_INDICE["sel_estado"]],
            artifact_ids=_lista(linha[_INDICE["sel_artefatos"]]),
            observation_ids=_lista(linha[_INDICE["sel_observacoes"]]),
            motivo=linha[_INDICE["sel_motivo"]] or "",
        ),
    )


def _avaliacao(contexto: ContextoSaida, linha: tuple[Any, ...]) -> RuleEvaluation:
    versoes = {regra.rule_id: regra.versao for regra in contexto.regras}
    evidencia = linha[_INDICE["ev_id"]]
    return RuleEvaluation(
        run_id=contexto.run_id,
        row_id=linha[_INDICE["row_id"]],
        rule_id=linha[_INDICE["rule_id"]],
        versao=versoes[linha[_INDICE["rule_id"]]],
        politica_id=contexto.politica.politica_id,
        metodo=contexto.politica.metodo,
        estado=linha[_INDICE["estado"]],
        aplicabilidade=linha[_INDICE["aplicabilidade"]],
        insumos_completos=linha[_INDICE["insumos_completos"]],
        incompatibilidade_demonstrada=linha[_INDICE["incompatibilidade_demonstrada"]],
        motivos=tuple(MotivoInconclusao(m) for m in _lista(linha[_INDICE["motivos"]])),
        selecoes=_selecoes(linha),
        evidence_ids=(evidencia,) if evidencia else (),
    )


def _linhas(con: duckdb.DuckDBPyConnection, consulta: str) -> Iterator[tuple[Any, ...]]:
    cursor = con.execute(consulta)
    while lote := cursor.fetchmany(_LOTE):
        yield from lote


def _validar_evidencias(con: duckdb.DuckDBPyConnection, contexto: ContextoSaida) -> set[str]:
    colunas = ", ".join(nome for nome, _ in COLUNAS_BRUTAS if nome.startswith("ev_"))
    consulta = (
        f"SELECT DISTINCT {colunas} FROM avaliacoes_brutas "  # noqa: S608
        "WHERE ev_id IS NOT NULL ORDER BY ev_id"
    )
    invalidas: set[str] = set()
    for linha in _linhas(con, consulta):
        try:
            Evidence(
                **dict(zip(COLUNAS_EVIDENCIAS, linha, strict=True))
                | {
                    "parametros": json.loads(linha[4]),
                    "artifact_ids": _lista(linha[7]),
                    "chaves_amostra": tuple(json.loads(linha[11])),
                }
            )
        except (ValidationError, ValueError, TypeError) as erro:
            invalidas.add(str(linha[0]))
            contexto.falhas.registrar("validar_evidencia", erro)
    return invalidas


def _validar_avaliacoes(
    con: duckdb.DuckDBPyConnection, contexto: ContextoSaida, evidencias_invalidas: set[str]
) -> tuple[set[tuple[str, str]], list[tuple[str, ...]]]:
    colunas = ", ".join(f"a.{nome}" for nome, _ in COLUNAS_BRUTAS[1:])
    consulta = (
        f"SELECT r.row_id, {colunas} FROM registros AS r "  # noqa: S608
        "LEFT JOIN avaliacoes_brutas AS a ON a.row_id = r.row_id ORDER BY r.row_id, a.rule_id"
    )
    invalidas: set[tuple[str, str]] = set()
    agregados: list[tuple[str, ...]] = []
    sem_agregado = bool(contexto.falhas.regras_com_falha)
    for row_id, grupo in itertools.groupby(_linhas(con, consulta), key=lambda linha: linha[0]):
        avaliacoes, completo = _avaliacoes_do_registro(contexto, list(grupo), evidencias_invalidas)
        invalidas |= {(row_id, rule_id) for rule_id in completo}
        if sem_agregado or completo:
            continue
        if len(avaliacoes) != len(contexto.regras):
            erro = ValueError(f"agregacao_incompleta avaliacoes={len(avaliacoes)}")
            contexto.falhas.registrar("agregar_registro", erro, row_id=row_id)
            continue
        agregado = AgregadoRegistro.agregar(contexto.run_id, row_id, avaliacoes)
        agregados.append(_linha_agregado(agregado))
    return invalidas, agregados


def _avaliacoes_do_registro(
    contexto: ContextoSaida, grupo: list[tuple[Any, ...]], evidencias_invalidas: set[str]
) -> tuple[list[RuleEvaluation], list[str]]:
    avaliacoes: list[RuleEvaluation] = []
    invalidas: list[str] = []
    for linha in grupo:
        rule_id = linha[_INDICE["rule_id"]]
        if rule_id is None:
            continue
        try:
            if linha[_INDICE["ev_id"]] in evidencias_invalidas:
                raise ValueError(
                    f"avaliacao_com_evidencia_invalida evidencia={linha[_INDICE['ev_id']]}"
                )
            avaliacoes.append(_avaliacao(contexto, linha))
        except (ValidationError, ValueError, TypeError) as erro:
            invalidas.append(rule_id)
            contexto.falhas.registrar("validar_avaliacao", erro, row_id=linha[0], rule_id=rule_id)
    return avaliacoes, invalidas


def _linha_agregado(agregado: AgregadoRegistro) -> tuple[str, ...]:
    return (
        agregado.run_id,
        agregado.row_id,
        ";".join(agregado.violacoes),
        ";".join(agregado.conformes),
        ";".join(agregado.inconclusivas),
        ";".join(agregado.nao_aplicaveis),
        str(agregado.resultado),
    )


def _criar_tabela(
    con: duckdb.DuckDBPyConnection,
    nome: str,
    colunas: dict[str, str],
    linhas: list[tuple[Any, ...]],
) -> None:
    definicao = ", ".join(f"{coluna} {tipo}" for coluna, tipo in colunas.items())
    con.execute(f"CREATE OR REPLACE TEMP TABLE {nome} ({definicao})")
    if linhas:
        marcadores = ", ".join("?" for _ in colunas)
        con.executemany(f"INSERT INTO {nome} VALUES ({marcadores})", linhas)  # noqa: S608


_SQL_SAIDAS = {
    "avaliacoes": (
        "SELECT $run_id AS run_id, a.row_id, a.rule_id, m.versao, $politica_id AS politica_id, "
        "$metodo AS metodo, a.estado, a.aplicabilidade, a.insumos_completos, "
        "a.incompatibilidade_demonstrada, a.motivos, coalesce(a.ev_id, '') AS evidence_ids "
        "FROM avaliacoes_brutas AS a JOIN regras_meta AS m ON m.rule_id = a.rule_id "
        "ORDER BY a.row_id, a.rule_id"
    ),
    "evidencias": (
        "SELECT DISTINCT ev_id AS evidence_id, ev_tipo AS tipo, ev_query_id AS query_id, "
        "ev_sql_sha256 AS sql_sha256, ev_parametros AS parametros, ev_dataset_id AS dataset_id, "
        "ev_hash_logico AS hash_logico, ev_artifact_ids AS artifact_ids, "
        "ev_cobertura AS cobertura, ev_integridade AS integridade, "
        "ev_n_resultados AS n_resultados, ev_chaves_amostra AS chaves_amostra "
        "FROM avaliacoes_brutas WHERE ev_id IS NOT NULL "
        "AND ev_id NOT IN (SELECT evidence_id FROM evidencias_invalidas) ORDER BY evidence_id"
    ),
    "selecao_versoes": (
        "SELECT $run_id AS run_id, row_id, rule_id, sel_fonte AS fonte, sel_base AS base, "
        "sel_competencia AS competencia_requerida, sel_estado AS estado, "
        "sel_artefatos AS artifact_ids, sel_observacoes AS observation_ids, "
        "sel_motivo AS motivo FROM avaliacoes_brutas WHERE sel_estado IS NOT NULL "
        "ORDER BY row_id, rule_id, fonte"
    ),
}
_PARAMETROS_SAIDA = {
    "avaliacoes": ("run_id", "politica_id", "metodo"),
    "evidencias": (),
    "selecao_versoes": ("run_id",),
}
_ESQUEMAS = {
    "avaliacoes": ("avaliacoes.v1", COLUNAS_AVALIACOES),
    "evidencias": ("evidencias.v1", COLUNAS_EVIDENCIAS),
    "selecao_versoes": ("selecao_versoes.v1", COLUNAS_SELECOES),
    "agregados_registro": ("agregados_registro.v1", COLUNAS_AGREGADOS),
    "falhas": ("falhas.v1", COLUNAS_FALHAS),
}


def _materializar(con: duckdb.DuckDBPyConnection, contexto: ContextoSaida) -> None:
    valores = {
        "run_id": contexto.run_id,
        "politica_id": contexto.politica.politica_id,
        "metodo": str(contexto.politica.metodo),
    }
    _criar_tabela(
        con,
        "regras_meta",
        {"rule_id": _TEXTO, "versao": _TEXTO},
        [(regra.rule_id, regra.versao) for regra in contexto.regras],
    )
    for nome, consulta in _SQL_SAIDAS.items():
        parametros = {chave: valores[chave] for chave in _PARAMETROS_SAIDA[nome]}
        con.execute(f"CREATE OR REPLACE TEMP TABLE saida_{nome} AS {consulta}", parametros)


def _artefatos(contexto: ContextoSaida) -> tuple[str, ...]:
    conjuntos = [contexto.dataset, *contexto.insumos.auxiliares]
    return tuple(sorted({a for d in conjuntos for a in d.artifact_ids}))


def _gravar(con: duckdb.DuckDBPyConnection, contexto: ContextoSaida, nome: str) -> DatasetRef:
    schema_id, colunas = _ESQUEMAS[nome]
    tabela = f"saida_{nome}"
    caminho = contexto.destino / f"{nome}.parquet"
    lista = ", ".join(colunas)
    con.sql(f"SELECT {lista} FROM {tabela}").write_parquet(str(caminho))  # noqa: S608
    hash_logico = hash_logico_relacao(con, tabela, colunas)
    linhas = con.execute(f"SELECT count(*) FROM {tabela}").fetchall()[0][0]  # noqa: S608
    artefatos = _artefatos(contexto)
    return DatasetRef(
        dataset_id=calcular_dataset_id(schema_id, hash_logico, artefatos),
        schema_id=schema_id,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=artefatos,
        origem_dados=contexto.dataset.origem_dados,
        produzido_por=contexto.run_id,
    )


def _linhas_falhas(contexto: ContextoSaida) -> list[tuple[Any, ...]]:
    return [
        (f.run_id, sequencia, f.etapa, f.row_id, f.rule_id, f.erro, f.ocorrida_em.isoformat())
        for sequencia, f in enumerate(contexto.falhas.falhas, start=1)
    ]


def gravar_saidas(
    con: duckdb.DuckDBPyConnection, contexto: ContextoSaida, *, avaliadas: bool
) -> tuple[DatasetRef, ...]:
    """Valida avaliações e evidências nos contratos e grava as cinco saídas em `destino`.

    Avaliação ou evidência que viola o contrato é removida e vira falha operacional; registro
    afetado por falha não recebe agregado.
    """
    agregados: list[tuple[str, ...]] = []
    evidencias_invalidas: set[str] = set()
    if avaliadas:
        evidencias_invalidas = _validar_evidencias(con, contexto)
        invalidas, agregados = _validar_avaliacoes(con, contexto, evidencias_invalidas)
        if invalidas:
            con.executemany(
                "DELETE FROM avaliacoes_brutas WHERE row_id = ? AND rule_id = ?", sorted(invalidas)
            )
    else:
        colunas = ", ".join(f"{nome} {tipo}" for nome, tipo in COLUNAS_BRUTAS)
        con.execute(f"CREATE TEMP TABLE IF NOT EXISTS avaliacoes_brutas ({colunas})")
    _criar_tabela(
        con,
        "evidencias_invalidas",
        {"evidence_id": _TEXTO},
        [(evidencia,) for evidencia in sorted(evidencias_invalidas)],
    )
    _materializar(con, contexto)
    _criar_tabela(
        con, "saida_agregados_registro", dict.fromkeys(COLUNAS_AGREGADOS, _TEXTO), agregados
    )
    tipos_falhas = dict.fromkeys(COLUNAS_FALHAS, _TEXTO) | {"sequencia": "BIGINT"}
    _criar_tabela(con, "saida_falhas", tipos_falhas, _linhas_falhas(contexto))
    saidas = tuple(_gravar(con, contexto, nome) for nome in _ESQUEMAS)
    logger.info("saidas_gravadas run=%s destino=%s", contexto.run_id, contexto.destino)
    return saidas
