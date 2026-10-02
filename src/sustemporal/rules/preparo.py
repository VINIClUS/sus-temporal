"""Carga dos insumos da avaliação no DuckDB, com chaves conferidas e nomes de allowlist."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.records import TipoCanonico
from sustemporal.duck import identificador_seguro
from sustemporal.rules.catalog import (
    MAPA_INSTRUMENTO_REGISTRO,
    carregar_esquema,
)
from sustemporal.rules.coerencia import SQL_REQUERIDAS, criar_regras_fontes

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import PoliticaTemporal, SnapshotSet

__all__ = [
    "COLUNAS_BASE_REGISTRO",
    "ERROS_DE_LEITURA",
    "carregar_cobertura",
    "carregar_integridade",
    "carregar_registros",
    "carregar_selecoes",
    "derivar_selecoes",
]

logger = logging.getLogger(__name__)

COLUNAS_BASE_REGISTRO = (
    "row_id",
    "artifact_id",
    "instrumento",
    "procedimento",
    "cbo",
    "cnes",
    "competencia_atendimento",
    "competencia_processamento",
)
_OBRIGATORIAS_REGISTRO = ("row_id", "artifact_id")
_COLUNAS_SELECAO = (
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
# Falhas de leitura de arquivo (ausente, truncado, não parquet): fonte inutilizável.
ERROS_DE_LEITURA: tuple[type[Exception], ...] = (
    duckdb.IOException,
    duckdb.InvalidInputException,
    FileNotFoundError,
)
_COMPETENCIA = "[0-9]{4}(0[1-9]|1[0-2])"
# model.md §3: código do registro fora do padrão conta como nulo em todos os passos.
_DOMINIO_REGISTRO = {
    "procedimento": "[0-9]{10}",
    "cbo": "[0-9A-Z]{6}",
    "cnes": "[0-9]{7}",
    "competencia_atendimento": _COMPETENCIA,
    "competencia_processamento": _COMPETENCIA,
}
_INTEIROS_FISICOS = frozenset(
    {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"}
)
_COLUNAS_COBERTURA = ("familia_regra", "instrumento", "competencia", "base_temporal", "estado")
_TIPO_SQL = {TipoCanonico.INTEIRO: "BIGINT", TipoCanonico.BOOLEANO: "BOOLEAN"}
_LISTA_NORMALIZADA = (
    "array_to_string(list_sort(list_distinct(list_filter("
    "string_split(coalesce({c}, ''), ';'), x -> x <> ''))), ';')"
)


def _tipos_do_parquet(con: duckdb.DuckDBPyConnection, caminho: str) -> dict[str, str]:
    descricao = con.execute("DESCRIBE SELECT * FROM read_parquet($c)", {"c": caminho}).fetchall()
    return {str(linha[0]): str(linha[1]) for linha in descricao}


def _tipo_compativel(esperado: str, fisico: str) -> bool:
    if esperado == "BIGINT":
        return fisico in _INTEIROS_FISICOS
    return fisico == esperado


def _incompativeis(
    colunas: Collection[str], fisicos: Mapping[str, str], tipos: Mapping[str, str]
) -> list[str]:
    return sorted(
        nome
        for nome in colunas
        if nome in fisicos and not _tipo_compativel(tipos[nome], fisicos[nome])
    )


def _conferir_tipos(
    con: duckdb.DuckDBPyConnection, caminho: str, schema_id: str, colunas: Collection[str]
) -> tuple[set[str], list[str]]:
    """Verificador único: colunas presentes e as de tipo físico diferente do esquema canônico.

    Aplicado a toda tabela de entrada antes de qualquer projeção ou cast.
    """
    fisicos = _tipos_do_parquet(con, caminho)
    return set(fisicos), _incompativeis(colunas, fisicos, _tipos(schema_id))


def _tipos(schema_id: str) -> dict[str, str]:
    esquema = carregar_esquema(schema_id)
    return {coluna.nome: _TIPO_SQL.get(coluna.tipo, "VARCHAR") for coluna in esquema.colunas}


def _projecao(colunas: Collection[str], presentes: set[str], tipos: Mapping[str, str]) -> str:
    partes = []
    for nome in colunas:
        citado = identificador_seguro(nome, tipos)
        origem = citado if nome in presentes else "NULL"
        partes.append(f"CAST({origem} AS {tipos[nome]}) AS {citado}")
    return ", ".join(partes)


def _projecao_registros(
    colunas: Collection[str], presentes: set[str], tipos: Mapping[str, str]
) -> str:
    partes = []
    for nome in colunas:
        citado = identificador_seguro(nome, tipos)
        texto = f"CAST({citado} AS {tipos[nome]})" if nome in presentes else "NULL"
        if nome in _DOMINIO_REGISTRO and nome in presentes:
            texto = f"CASE WHEN regexp_full_match({texto}, $dominio_{nome}) THEN {texto} END"
        partes.append(f"CAST({texto} AS {tipos[nome]}) AS {citado}")
    return ", ".join(partes)


def _chaves_nulas(
    con: duckdb.DuckDBPyConnection, tabela: str, chave: tuple[str, ...], tipos: Mapping[str, str]
) -> int:
    tabela_sql = identificador_seguro(tabela, {tabela})
    condicao = " OR ".join(f"{identificador_seguro(nome, tipos)} IS NULL" for nome in chave)
    resultado = con.execute(
        f"SELECT count(*) FROM {tabela_sql} WHERE {condicao}"  # noqa: S608
    ).fetchall()[0][0]
    return int(resultado)


def _exigir_chave_unica(
    con: duckdb.DuckDBPyConnection, tabela: str, chave: tuple[str, ...], tipos: Mapping[str, str]
) -> None:
    """Recusa chave nula ou repetida (falha de carga).

    Raises:
        ValueError: alguma coluna da chave nula ou combinação repetida.
    """
    nulas = _chaves_nulas(con, tabela, chave, tipos)
    if nulas:
        raise ValueError(f"chave_nula tabela={tabela} linhas={nulas}")
    tabela_sql = identificador_seguro(tabela, {tabela})
    colunas = ", ".join(identificador_seguro(nome, tipos) for nome in chave)
    repetidas = con.execute(
        f"SELECT count(*) FROM (SELECT {colunas} FROM {tabela_sql} "  # noqa: S608
        f"GROUP BY {colunas} HAVING count(*) > 1)"
    ).fetchall()[0][0]
    if repetidas:
        raise ValueError(f"chave_repetida tabela={tabela} chaves={repetidas}")


def carregar_registros(
    con: duckdb.DuckDBPyConnection, dataset: DatasetRef, regras: list[RuleSpec]
) -> frozenset[str]:
    """Cria `registros` com as colunas usadas; coluna ausente vira nula (campo insuficiente).

    Raises:
        ValueError: sem `row_id`/`artifact_id` ou `row_id` repetido.
    """
    tipos = _tipos("sia_pa.v1")
    usadas = dict.fromkeys(COLUNAS_BASE_REGISTRO)
    usadas.update(dict.fromkeys(campo for regra in regras for campo in regra.campos_necessarios))
    presentes, incompativeis = _conferir_tipos(con, dataset.caminho, "sia_pa.v1", usadas)
    faltantes = [nome for nome in _OBRIGATORIAS_REGISTRO if nome not in presentes]
    if faltantes:
        raise ValueError(f"registros_sem_coluna_obrigatoria colunas={faltantes}")
    if incompativeis:
        raise ValueError(f"registros_com_tipo_incompativel colunas={incompativeis}")
    projecao = _projecao_registros(list(usadas), presentes, tipos)
    dominios = {
        f"dominio_{nome}": padrao
        for nome, padrao in _DOMINIO_REGISTRO.items()
        if nome in usadas and nome in presentes
    }
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE registros AS SELECT {projecao} "  # noqa: S608
        "FROM read_parquet($c)",
        {"c": dataset.caminho} | dominios,
    )
    _exigir_chave_unica(con, "registros", ("row_id",), tipos)
    return frozenset(presentes & set(usadas))


def carregar_selecoes(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    """Cria `selecoes` a partir de uma tabela `selecao_versoes.v1` pronta (sem o `run_id`).

    Raises:
        ValueError: coluna ausente ou chave (row_id, rule_id, fonte) repetida.
    """
    tipos = _tipos("selecao_versoes.v1")
    presentes, incompativeis = _conferir_tipos(
        con, dataset.caminho, "selecao_versoes.v1", _COLUNAS_SELECAO
    )
    faltantes = sorted(set(_COLUNAS_SELECAO) - presentes)
    if faltantes:
        raise ValueError(f"selecoes_sem_coluna colunas={faltantes}")
    if incompativeis:
        raise ValueError(f"selecoes_com_tipo_incompativel colunas={incompativeis}")
    partes = []
    for nome in _COLUNAS_SELECAO:
        citado = identificador_seguro(nome, tipos)
        normalizado = nome in {"artifact_ids", "observation_ids"}
        expressao = _LISTA_NORMALIZADA.format(c=citado) if normalizado else citado
        partes.append(f"{expressao} AS {citado}")
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE selecoes AS SELECT {', '.join(partes)} "  # noqa: S608
        "FROM read_parquet($c)",
        {"c": dataset.caminho},
    )
    _exigir_chave_unica(con, "selecoes", ("row_id", "rule_id", "fonte"), tipos)


_SQL_DERIVAR = f"""
CREATE OR REPLACE TEMP TABLE selecoes AS
WITH {SQL_REQUERIDAS}
SELECT
    q.row_id, q.rule_id, q.fonte,
    CASE WHEN q.comp IS NULL THEN NULL ELSE q.base END AS base,
    q.comp AS competencia_requerida,
    CASE WHEN q.comp IS NULL THEN 'NAO_RESOLVIDA' ELSE coalesce(s.estado, 'AUSENTE') END AS estado,
    CASE WHEN q.comp IS NULL THEN '' ELSE coalesce(s.artifact_ids, '') END AS artifact_ids,
    CASE WHEN q.comp IS NULL THEN '' ELSE coalesce(s.observation_ids, '') END AS observation_ids,
    CASE
        WHEN q.base IS NULL THEN 'politica_sem_criterio_para_a_fonte fonte=' || q.fonte
        WHEN q.comp IS NULL THEN 'competencia_base_ausente base=' || q.base
        WHEN s.estado IS NULL THEN 'sem_selecao_no_snapshot competencia=' || q.comp
        ELSE s.motivo
    END AS motivo
FROM requeridas AS q
LEFT JOIN snapshot_selecoes AS s
    ON s.fonte = q.fonte AND s.base = q.base AND s.competencia_requerida = q.comp
"""  # noqa: S608


def derivar_selecoes(
    con: duckdb.DuckDBPyConnection,
    snapshots: SnapshotSet,
    regras: list[RuleSpec],
    politica: PoliticaTemporal,
) -> None:
    """Seleção por correspondência exata (fonte, base, competência) no `SnapshotSet` (model.md §5).

    Raises:
        ValueError: duas seleções do `SnapshotSet` com a mesma fonte, base e competência.
    """
    entradas = [
        (
            str(s.fonte),
            str(s.base),
            str(s.competencia_requerida),
            str(s.estado),
            ";".join(sorted(set(s.artifact_ids))),
            ";".join(sorted(set(s.observation_ids))),
            s.motivo,
        )
        for s in snapshots.selecoes
        if s.base is not None and s.competencia_requerida is not None
    ]
    chaves = [entrada[:3] for entrada in entradas]
    if len(set(chaves)) != len(chaves):
        raise ValueError("snapshot_com_selecao_repetida_por_fonte_base_competencia")
    con.execute(
        "CREATE OR REPLACE TEMP TABLE snapshot_selecoes (fonte VARCHAR, base VARCHAR, "
        "competencia_requerida VARCHAR, estado VARCHAR, artifact_ids VARCHAR, "
        "observation_ids VARCHAR, motivo VARCHAR)"
    )
    if entradas:
        con.executemany("INSERT INTO snapshot_selecoes VALUES (?, ?, ?, ?, ?, ?, ?)", entradas)
    criar_regras_fontes(con, regras, politica)
    con.execute(_SQL_DERIVAR)


def carregar_cobertura(con: duckdb.DuckDBPyConnection, dataset: DatasetRef | None) -> None:
    """Cria `cobertura`; vazia sem matriz utilizável (ausência nunca sustenta violação).

    Não é utilizável a matriz com coluna ausente, de tipo físico diferente do esquema canônico
    ou com chave nula.

    Raises:
        ValueError: chave repetida.
    """
    tipos = _tipos("cobertura.v1")
    if dataset is None:
        _cobertura_vazia(con, tipos)
        return
    try:
        presentes, incompativeis = _conferir_tipos(
            con, dataset.caminho, "cobertura.v1", _COLUNAS_COBERTURA
        )
    except ERROS_DE_LEITURA:
        _motivo_ilegivel(dataset.caminho)
        _cobertura_vazia(con, tipos)
        return
    faltantes = sorted(set(_COLUNAS_COBERTURA) - presentes)
    if faltantes or incompativeis:
        logger.warning("cobertura_nao_utilizavel faltantes=%s tipos=%s", faltantes, incompativeis)
        _cobertura_vazia(con, tipos)
        return
    projecao = _projecao(_COLUNAS_COBERTURA, presentes, tipos)
    try:
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE cobertura AS SELECT {projecao} "  # noqa: S608
            "FROM read_parquet($c)",
            {"c": dataset.caminho},
        )
    except ERROS_DE_LEITURA:
        _motivo_ilegivel(dataset.caminho)
        _cobertura_vazia(con, tipos)
        return
    nulas = _chaves_nulas(con, "cobertura", _COLUNAS_COBERTURA[:4], tipos)
    if nulas:
        logger.warning("cobertura_nao_utilizavel chaves_nulas=%d", nulas)
        _cobertura_vazia(con, tipos)
        return
    _exigir_chave_unica(con, "cobertura", _COLUNAS_COBERTURA[:4], tipos)


def _cobertura_vazia(con: duckdb.DuckDBPyConnection, tipos: Mapping[str, str]) -> None:
    colunas = ", ".join(f"{identificador_seguro(c, tipos)} VARCHAR" for c in _COLUNAS_COBERTURA)
    con.execute(f"CREATE OR REPLACE TEMP TABLE cobertura ({colunas})")


def carregar_integridade(
    con: duckdb.DuckDBPyConnection, integridade: Mapping[str, EstadoIntegridade]
) -> None:
    """Cria `integridade` e `mapa_registro` (constantes da execução).

    Raises:
        ValueError: chave que não é texto ou estado que não é `EstadoIntegridade`.
    """
    invalidos = sorted(
        repr(artefato)
        for artefato, estado in integridade.items()
        if not isinstance(artefato, str) or not isinstance(estado, EstadoIntegridade)
    )
    if invalidos:
        raise ValueError(f"integridade_com_tipo_incompativel artefatos={invalidos}")
    con.execute("CREATE OR REPLACE TEMP TABLE integridade (artifact_id VARCHAR, estado VARCHAR)")
    linhas = sorted((artefato, str(estado)) for artefato, estado in integridade.items())
    if linhas:
        con.executemany("INSERT INTO integridade VALUES (?, ?)", linhas)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE mapa_registro (instrumento VARCHAR, co_registro VARCHAR)"
    )
    con.executemany(
        "INSERT INTO mapa_registro VALUES (?, ?)", sorted(MAPA_INSTRUMENTO_REGISTRO.items())
    )


def _motivo_ilegivel(caminho: str) -> str:
    motivo = "ARQUIVO_AUSENTE" if not Path(caminho).is_file() else "ARQUIVO_EM_QUARENTENA"
    logger.warning("fonte_ilegivel caminho=%s motivo=%s", caminho, motivo)
    return motivo
