"""Carga de cada conjunto auxiliar de uma regra: leiaute, leitura e conjuntos selecionados."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.rules.catalog import requisito_auxiliar
from sustemporal.rules.preparo import (
    ERROS_DE_LEITURA,
    _conferir_tipos,
    _motivo_ilegivel,
    _projecao,
    _tipos,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    import duckdb

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec

__all__ = ["Auxiliar", "preparar_auxiliar", "preparar_conjuntos"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Auxiliar:
    """Conjunto auxiliar de uma regra e o estado do seu leiaute (`OK` ou motivo de inconclusão)."""

    dataset: DatasetRef | None
    leiaute: str


def _leiaute_auxiliar(
    con: duckdb.DuckDBPyConnection,
    dataset: DatasetRef | None,
    schema_id: str,
    colunas: list[str],
) -> tuple[str, set[str]]:
    if dataset is None:
        return "ARQUIVO_AUSENTE", set()
    try:
        presentes, incompativeis = _conferir_tipos(con, dataset.caminho, schema_id, colunas)
    except ERROS_DE_LEITURA:
        return _motivo_ilegivel(dataset.caminho), set()
    if not set(colunas) <= presentes or incompativeis:
        return "LEIAUTE_INCOMPATIVEL", presentes
    return "OK", presentes


def _criar_aux(con: duckdb.DuckDBPyConnection, projecao: str, caminho: str | None) -> None:
    origem = "read_parquet($c)" if caminho is not None else "(SELECT 1) WHERE false"
    parametros = {"c": caminho} if caminho is not None else {}
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE aux AS SELECT {projecao} FROM {origem}",  # noqa: S608
        parametros,
    )


def preparar_auxiliar(
    con: duckdb.DuckDBPyConnection, regra: RuleSpec, auxiliares: tuple[DatasetRef, ...]
) -> Auxiliar:
    """Cria `aux` com as colunas do requisito; vazia quando o leiaute não permite consultar.

    Raises:
        ValueError: mais de um conjunto auxiliar com o `schema_id` do requisito.
    """
    requisito = requisito_auxiliar(regra)
    tipos = _tipos(requisito.schema_id)
    colunas = list(dict.fromkeys(["artifact_id", *requisito.campos]))
    candidatos = [d for d in auxiliares if d.schema_id == requisito.schema_id]
    if len(candidatos) > 1:
        raise ValueError(f"auxiliar_repetido schema_id={requisito.schema_id}")
    dataset = candidatos[0] if candidatos else None
    leiaute, presentes = _leiaute_auxiliar(con, dataset, requisito.schema_id, colunas)
    if leiaute == "OK" and dataset is not None:
        try:
            _criar_aux(con, _projecao(colunas, presentes, tipos), dataset.caminho)
        except ERROS_DE_LEITURA:
            leiaute = _motivo_ilegivel(dataset.caminho)
    if leiaute != "OK":
        _criar_aux(con, _projecao(colunas, set(), tipos), None)
    logger.info("auxiliar_preparado regra=%s leiaute=%s", regra.rule_id, leiaute)
    return Auxiliar(dataset=dataset, leiaute=leiaute)


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
    return (
        fora,
        quarentena,
        vazio,
        todas,
        "OK" if ok else (ruins[0] if ruins else "NAO_VERIFICADO"),
        ok,
    )


def preparar_conjuntos(
    con: duckdb.DuckDBPyConnection,
    regra: RuleSpec,
    auxiliar: Auxiliar,
    integridade: Mapping[str, EstadoIntegridade],
) -> None:
    """Cria `conjuntos`: por conjunto de versões selecionadas, escopo, presença e integridade."""
    chaves = con.execute(
        "SELECT DISTINCT artifact_ids FROM selecoes "
        "WHERE rule_id = $r AND estado = 'SELECIONADA' ORDER BY artifact_ids",
        {"r": regra.rule_id},
    ).fetchall()
    com_linhas = {
        str(linha[0]) for linha in con.execute("SELECT DISTINCT artifact_id FROM aux").fetchall()
    }
    linhas = []
    for (chave,) in chaves:
        artefatos = [a for a in str(chave or "").split(";") if a]
        linhas.append((chave, *_estado_do_conjunto(artefatos, auxiliar, com_linhas, integridade)))
    con.execute(
        "CREATE OR REPLACE TEMP TABLE conjuntos (chave VARCHAR, fora BOOLEAN, quarentena BOOLEAN, "
        "escopo_vazio BOOLEAN, todas_com_linhas BOOLEAN, integridade VARCHAR, "
        "integridade_ok BOOLEAN)"
    )
    if linhas:
        con.executemany("INSERT INTO conjuntos VALUES (?, ?, ?, ?, ?, ?, ?)", linhas)
