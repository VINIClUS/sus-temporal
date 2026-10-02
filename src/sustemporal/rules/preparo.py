"""Carga dos insumos da avaliação no DuckDB, com chaves conferidas e nomes de allowlist."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.records import TipoCanonico
from sustemporal.duck import identificador_seguro
from sustemporal.rules.catalog import (
    MAPA_INSTRUMENTO_REGISTRO,
    carregar_esquema,
    requisito_auxiliar,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    import duckdb

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import PoliticaTemporal, SnapshotSet

__all__ = [
    "COLUNAS_BASE_REGISTRO",
    "Auxiliar",
    "carregar_cobertura",
    "carregar_integridade",
    "carregar_registros",
    "carregar_selecoes",
    "derivar_selecoes",
    "preparar_auxiliar",
    "preparar_conjuntos",
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
_COMPETENCIA = "[0-9]{4}(0[1-9]|1[0-2])"
# model.md §3: código do registro fora do padrão conta como nulo em todos os passos.
_DOMINIO_REGISTRO = {
    "procedimento": "[0-9]{10}",
    "cbo": "[0-9A-Z]{6}",
    "cnes": "[0-9]{7}",
    "competencia_atendimento": _COMPETENCIA,
    "competencia_processamento": _COMPETENCIA,
}
_COLUNAS_COBERTURA = ("familia_regra", "instrumento", "competencia", "base_temporal", "estado")
_TIPO_SQL = {TipoCanonico.INTEIRO: "BIGINT", TipoCanonico.BOOLEANO: "BOOLEAN"}
_LISTA_NORMALIZADA = (
    "array_to_string(list_sort(list_distinct(list_filter("
    "string_split(coalesce({c}, ''), ';'), x -> x <> ''))), ';')"
)


@dataclass(frozen=True)
class Auxiliar:
    """Conjunto auxiliar de uma regra e o estado do seu leiaute (`OK` ou motivo de inconclusão)."""

    dataset: DatasetRef | None
    leiaute: str


def _colunas_do_parquet(con: duckdb.DuckDBPyConnection, caminho: str) -> set[str]:
    descricao = con.execute("DESCRIBE SELECT * FROM read_parquet($c)", {"c": caminho}).fetchall()
    return {str(linha[0]) for linha in descricao}


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


def _exigir_chave_unica(
    con: duckdb.DuckDBPyConnection, tabela: str, chave: tuple[str, ...], tipos: Mapping[str, str]
) -> None:
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
    presentes = _colunas_do_parquet(con, dataset.caminho)
    faltantes = [nome for nome in _OBRIGATORIAS_REGISTRO if nome not in presentes]
    if faltantes:
        raise ValueError(f"registros_sem_coluna_obrigatoria colunas={faltantes}")
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
    presentes = _colunas_do_parquet(con, dataset.caminho)
    faltantes = sorted(set(_COLUNAS_SELECAO) - presentes)
    if faltantes:
        raise ValueError(f"selecoes_sem_coluna colunas={faltantes}")
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


_SQL_DERIVAR = """
CREATE OR REPLACE TEMP TABLE selecoes AS
WITH pedidos AS (
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
"""


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
    criterios = {criterio.fonte: criterio for criterio in politica.criterios}
    pedidos = []
    for regra in regras:
        fonte = requisito_auxiliar(regra).fonte
        criterio = criterios.get(fonte)
        base = str(criterio.base) if criterio else None
        pedidos.append(
            (regra.rule_id, str(fonte), base, criterio.deslocamento_meses if criterio else 0)
        )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE snapshot_selecoes (fonte VARCHAR, base VARCHAR, "
        "competencia_requerida VARCHAR, estado VARCHAR, artifact_ids VARCHAR, "
        "observation_ids VARCHAR, motivo VARCHAR)"
    )
    if entradas:
        con.executemany("INSERT INTO snapshot_selecoes VALUES (?, ?, ?, ?, ?, ?, ?)", entradas)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE regras_fontes "
        "(rule_id VARCHAR, fonte VARCHAR, base VARCHAR, deslocamento BIGINT)"
    )
    if pedidos:
        con.executemany("INSERT INTO regras_fontes VALUES (?, ?, ?, ?)", pedidos)
    con.execute(_SQL_DERIVAR)


def carregar_cobertura(con: duckdb.DuckDBPyConnection, dataset: DatasetRef | None) -> None:
    """Cria `cobertura` (vazia sem matriz: ausência nunca sustenta violação).

    Raises:
        ValueError: coluna ausente ou chave repetida.
    """
    tipos = _tipos("cobertura.v1")
    if dataset is None:
        colunas = ", ".join(f"{identificador_seguro(c, tipos)} VARCHAR" for c in _COLUNAS_COBERTURA)
        con.execute(f"CREATE OR REPLACE TEMP TABLE cobertura ({colunas})")
        return
    presentes = _colunas_do_parquet(con, dataset.caminho)
    faltantes = sorted(set(_COLUNAS_COBERTURA) - presentes)
    if faltantes:
        raise ValueError(f"cobertura_sem_coluna colunas={faltantes}")
    projecao = _projecao(_COLUNAS_COBERTURA, presentes, tipos)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE cobertura AS SELECT {projecao} "  # noqa: S608
        "FROM read_parquet($c)",
        {"c": dataset.caminho},
    )
    _exigir_chave_unica(con, "cobertura", _COLUNAS_COBERTURA[:4], tipos)


def carregar_integridade(
    con: duckdb.DuckDBPyConnection, integridade: Mapping[str, EstadoIntegridade]
) -> None:
    """Cria `integridade` e `mapa_registro` (constantes da execução)."""
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
    presentes = _colunas_do_parquet(con, dataset.caminho) if dataset else set()
    leiaute = "OK"
    if dataset is None:
        leiaute = "ARQUIVO_AUSENTE"
    elif not set(colunas) <= presentes:
        leiaute = "LEIAUTE_INCOMPATIVEL"
    projecao = _projecao(colunas, presentes if leiaute == "OK" else set(), tipos)
    origem = "read_parquet($c)" if leiaute == "OK" else "(SELECT 1) WHERE false"
    parametros = {"c": dataset.caminho} if leiaute == "OK" and dataset else {}
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE aux AS SELECT {projecao} FROM {origem}",  # noqa: S608
        parametros,
    )
    logger.info("auxiliar_preparado regra=%s leiaute=%s", regra.rule_id, leiaute)
    return Auxiliar(dataset=dataset, leiaute=leiaute)


def _estado_do_conjunto(
    artefatos: list[str],
    auxiliar: Auxiliar,
    com_linhas: set[str],
    integridade: Mapping[str, EstadoIntegridade],
) -> tuple[bool, bool, bool, str, bool]:
    conhecidos = set(auxiliar.dataset.artifact_ids) if auxiliar.dataset else set()
    fora = any(artefato not in conhecidos for artefato in artefatos)
    vazio = not any(artefato in com_linhas for artefato in artefatos)
    todas = bool(artefatos) and all(artefato in com_linhas for artefato in artefatos)
    estados = [integridade.get(artefato) for artefato in artefatos]
    ok = bool(estados) and all(estado is EstadoIntegridade.OK for estado in estados)
    ruins = sorted(
        str(e) if e is not None else "NAO_VERIFICADO"
        for e in estados
        if e is not EstadoIntegridade.OK
    )
    return fora, vazio, todas, "OK" if ok else (ruins[0] if ruins else "NAO_VERIFICADO"), ok


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
        "CREATE OR REPLACE TEMP TABLE conjuntos (chave VARCHAR, fora BOOLEAN, "
        "escopo_vazio BOOLEAN, todas_com_linhas BOOLEAN, integridade VARCHAR, "
        "integridade_ok BOOLEAN)"
    )
    if linhas:
        con.executemany("INSERT INTO conjuntos VALUES (?, ?, ?, ?, ?, ?)", linhas)
