"""Conjunto auxiliar de uma regra: conteúdo, leiaute, domínio e versões selecionadas."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.duck import identificador_seguro
from sustemporal.rules.catalog import requisito_auxiliar
from sustemporal.rules.conteudo import verificar_conteudo
from sustemporal.rules.preparo import COMPETENCIA, _conferir_tipos, _projecao, _tipos

if TYPE_CHECKING:
    from collections.abc import Mapping

    import duckdb

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec

__all__ = ["DOMINIO_AUXILIAR", "Auxiliar", "preparar_auxiliar", "preparar_conjuntos"]

logger = logging.getLogger(__name__)

# model.md §3, passo 8: valor não nulo fora do domínio torna o conjunto LEIAUTE_INCOMPATIVEL.
DOMINIO_AUXILIAR = {
    "co_procedimento": "[0-9]{10}",
    "co_ocupacao": "[0-9A-Z]{6}",
    "cbo": "[0-9A-Z]{6}",
    "cnes": "[0-9]{7}",
    "co_registro": "[0-9]{2}",
    "dt_competencia": COMPETENCIA,
    "competencia_arquivo": COMPETENCIA,
}
_COLUNAS_COMPETENCIA = ("dt_competencia", "competencia_arquivo")


@dataclass(frozen=True)
class Auxiliar:
    """Conjunto auxiliar de uma regra e o estado do seu leiaute (`OK` ou motivo de inconclusão)."""

    dataset: DatasetRef | None
    leiaute: str
    coluna_competencia: str | None = None


def _criar_aux(con: duckdb.DuckDBPyConnection, projecao: str, caminho: str | None) -> None:
    origem = "read_parquet($c)" if caminho is not None else "(SELECT 1) WHERE false"
    parametros = {"c": caminho} if caminho is not None else {}
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE aux AS SELECT {projecao} FROM {origem}",  # noqa: S608
        parametros,
    )


def _fora_do_dominio(con: duckdb.DuckDBPyConnection, colunas: list[str]) -> list[str]:
    fora = []
    for nome in colunas:
        padrao = DOMINIO_AUXILIAR.get(nome)
        if padrao is None:
            continue
        citado = identificador_seguro(nome, colunas)
        quantidade = con.execute(
            f"SELECT count(*) FROM aux WHERE {citado} IS NOT NULL "  # noqa: S608
            f"AND NOT regexp_full_match({citado}, $padrao)",
            {"padrao": padrao},
        ).fetchall()[0][0]
        if quantidade:
            fora.append(nome)
    return fora


def _leiaute(
    con: duckdb.DuckDBPyConnection, dataset: DatasetRef | None, schema_id: str, colunas: list[str]
) -> tuple[str, set[str]]:
    if dataset is None:
        return "ARQUIVO_AUSENTE", set()
    verificar_conteudo(con, dataset)
    presentes, incompativeis = _conferir_tipos(con, dataset.caminho, schema_id, colunas)
    if not set(colunas) <= presentes or incompativeis:
        return "LEIAUTE_INCOMPATIVEL", presentes
    return "OK", presentes


def preparar_auxiliar(
    con: duckdb.DuckDBPyConnection, regra: RuleSpec, auxiliares: tuple[DatasetRef, ...]
) -> Auxiliar:
    """Cria `aux` com as colunas do requisito; vazia quando o leiaute não permite consultar.

    Raises:
        ValueError: mais de um conjunto para o `schema_id` do requisito ou conteúdo divergente.
    """
    requisito = requisito_auxiliar(regra)
    tipos = _tipos(requisito.schema_id)
    colunas = list(dict.fromkeys(["artifact_id", *requisito.campos]))
    candidatos = [d for d in auxiliares if d.schema_id == requisito.schema_id]
    if len(candidatos) > 1:
        raise ValueError(f"auxiliar_repetido schema_id={requisito.schema_id}")
    dataset = candidatos[0] if candidatos else None
    leiaute, presentes = _leiaute(con, dataset, requisito.schema_id, colunas)
    if leiaute == "OK" and dataset is not None:
        _criar_aux(con, _projecao(colunas, presentes, tipos), dataset.caminho)
        fora = _fora_do_dominio(con, colunas)
        if fora:
            logger.warning("auxiliar_fora_do_dominio regra=%s colunas=%s", regra.rule_id, fora)
            leiaute = "LEIAUTE_INCOMPATIVEL"
    if leiaute != "OK":
        _criar_aux(con, _projecao(colunas, set(), tipos), None)
    competencia = next((c for c in _COLUNAS_COMPETENCIA if c in colunas), None)
    logger.info("auxiliar_preparado regra=%s leiaute=%s", regra.rule_id, leiaute)
    return Auxiliar(dataset=dataset, leiaute=leiaute, coluna_competencia=competencia)


def _estado_do_conjunto(
    artefatos: list[str],
    auxiliar: Auxiliar,
    com_linhas: set[str],
    integridade: Mapping[str, EstadoIntegridade],
) -> tuple[bool, bool, bool, bool, str, bool]:
    conhecidos = set(auxiliar.dataset.artifact_ids) if auxiliar.dataset else set()
    fora = any(artefato not in conhecidos for artefato in artefatos)
    vazio = not any(artefato in com_linhas for artefato in artefatos)
    todas = bool(artefatos) and all(artefato in com_linhas for artefato in artefatos)
    estados = [integridade.get(artefato) for artefato in artefatos]
    quarentena = any(e is not None and e.value.startswith("QUARENTENA_") for e in estados)
    ok = bool(estados) and all(estado is EstadoIntegridade.OK for estado in estados)
    ruins = sorted(
        str(e) if e is not None else "NAO_VERIFICADO"
        for e in estados
        if e is not EstadoIntegridade.OK
    )
    pior = "OK" if ok else (ruins[0] if ruins else "NAO_VERIFICADO")
    return fora, quarentena, vazio, todas, pior, ok


def _competencia_divergente(
    con: duckdb.DuckDBPyConnection, auxiliar: Auxiliar, artefatos: list[str], competencia: str
) -> bool:
    coluna = auxiliar.coluna_competencia
    if coluna is None or not artefatos:
        return False
    citado = identificador_seguro(coluna, _COLUNAS_COMPETENCIA)
    quantidade = con.execute(
        f"SELECT count(*) FROM aux WHERE list_contains($artefatos, artifact_id) "  # noqa: S608
        f"AND ({citado} IS NULL OR {citado} <> $competencia)",
        {"artefatos": artefatos, "competencia": competencia},
    ).fetchall()[0][0]
    return bool(quantidade)


def preparar_conjuntos(
    con: duckdb.DuckDBPyConnection,
    regra: RuleSpec,
    auxiliar: Auxiliar,
    integridade: Mapping[str, EstadoIntegridade],
) -> None:
    """Cria `conjuntos`: por versões selecionadas e competência requerida, escopo e integridade."""
    chaves = con.execute(
        "SELECT DISTINCT artifact_ids, competencia_requerida FROM selecoes "
        "WHERE rule_id = $r AND estado = 'SELECIONADA' ORDER BY ALL",
        {"r": regra.rule_id},
    ).fetchall()
    com_linhas = {
        str(linha[0]) for linha in con.execute("SELECT DISTINCT artifact_id FROM aux").fetchall()
    }
    linhas = []
    for chave, competencia in chaves:
        artefatos = [a for a in str(chave or "").split(";") if a]
        estado = _estado_do_conjunto(artefatos, auxiliar, com_linhas, integridade)
        divergente = _competencia_divergente(con, auxiliar, artefatos, str(competencia))
        linhas.append((chave, competencia, divergente, *estado))
    con.execute(
        "CREATE OR REPLACE TEMP TABLE conjuntos (chave VARCHAR, competencia VARCHAR, "
        "competencia_divergente BOOLEAN, fora BOOLEAN, quarentena BOOLEAN, escopo_vazio BOOLEAN, "
        "todas_com_linhas BOOLEAN, integridade VARCHAR, integridade_ok BOOLEAN)"
    )
    if linhas:
        con.executemany("INSERT INTO conjuntos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", linhas)
