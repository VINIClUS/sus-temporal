"""Leitura conferida da população, dos rótulos e das saídas das execuções (T11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb

from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.baselines import SCHEMA_PREDICOES
from sustemporal.evaluation.metrics_calculo import NAO_APROVADO, LinhaAvaliada, Situacao
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sustemporal.contracts import DatasetRef, RunResult
    from sustemporal.contracts.experiment import Particao

__all__ = ["SCHEMA_AGREGADOS", "ler_populacao", "ler_situacoes", "verificar_entrada"]

SCHEMA_AGREGADOS = "agregados_registro.v1"
_BINARIOS = frozenset({NAO_APROVADO, "APROVADO_TOTAL"})
_SITUACOES = {
    "ALERTA": Situacao.ALERTA,
    "SEM_VIOLACAO_VERIFICADA": Situacao.SEM_ALERTA,
    "SEM_ALERTA": Situacao.SEM_ALERTA,
    "ABSTENCAO": Situacao.ABSTENCAO,
}


def _verificar_predicoes(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    colunas = [c.nome for c in SCHEMA_PREDICOES.colunas]
    con.execute(
        "CREATE OR REPLACE TEMP TABLE conferencia_predicoes AS "
        "SELECT run_id, row_id, metodo, particao, escore, resultado FROM read_parquet($c)",
        {"c": dataset.caminho},
    )
    try:
        linhas = int(con.execute("SELECT count(*) FROM conferencia_predicoes").fetchall()[0][0])
        obtido = hash_logico_relacao(con, "conferencia_predicoes", colunas)
    finally:
        con.execute("DROP TABLE IF EXISTS conferencia_predicoes")
    if (linhas, obtido) != (dataset.linhas, dataset.hash_logico):
        raise ConteudoDivergente(f"conteudo_divergente schema={dataset.schema_id}")


def verificar_entrada(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    """Confere linhas e hash lógico; arquivo ilegível ou divergente é falha operacional.

    Raises:
        FalhaOperacionalErro: conteúdo diferente do `DatasetRef` ou arquivo ilegível.
    """
    try:
        if dataset.schema_id == SCHEMA_PREDICOES.schema_id:
            _verificar_predicoes(con, dataset)
        else:
            verificar_conteudo(con, dataset)
    except (ConteudoDivergente, duckdb.Error) as erro:
        raise FalhaOperacionalErro(
            f"avaliacao_entrada_ilegivel_ou_divergente dataset={dataset.dataset_id} erro={erro}"
        ) from erro


def ler_populacao(
    con: duckdb.DuckDBPyConnection,
    populacao: DatasetRef,
    labels: DatasetRef,
    causas: Mapping[str, str],
) -> list[LinhaAvaliada]:
    """Linhas da partição com rótulo, estratos e pertença ao domínio comum.

    Raises:
        FalhaOperacionalErro: rótulos com row_id fora da partição, ausente ou repetido.
    """
    _exigir_mesmos_row_ids(con, populacao, labels)
    cursor = con.execute(
        "SELECT p.row_id, r.rotulo, p.cnes, p.competencia_processamento, p.instrumento, "
        "p.procedimento, p.cbo, p.competencia_atendimento FROM read_parquet($p) p "
        "LEFT JOIN read_parquet($r) r ON p.row_id = r.row_id ORDER BY p.row_id",
        {"p": populacao.caminho, "r": labels.caminho},
    )
    linhas = []
    for row_id, rotulo, cnes, competencia, instrumento, *demais in cursor.fetchall():
        observaveis = (cnes, instrumento, *demais)
        linhas.append(
            LinhaAvaliada(
                row_id=str(row_id),
                rotulo=rotulo,
                cnes=cnes,
                competencia=competencia,
                instrumento=instrumento,
                no_dominio_comum=rotulo in _BINARIOS
                and all(valor is not None for valor in observaveis),
                causa=causas.get(str(row_id)),
            )
        )
    return linhas


def _exigir_mesmos_row_ids(
    con: duckdb.DuckDBPyConnection, populacao: DatasetRef, labels: DatasetRef
) -> None:
    contagem = con.execute(
        "SELECT (SELECT count(*) - count(DISTINCT row_id) FROM read_parquet($r)) + "
        "(SELECT count(*) FROM ((SELECT row_id FROM read_parquet($r) EXCEPT "
        "SELECT row_id FROM read_parquet($p)) UNION ALL (SELECT row_id FROM read_parquet($p) "
        "EXCEPT SELECT row_id FROM read_parquet($r))))",
        {"p": populacao.caminho, "r": labels.caminho},
    ).fetchall()[0][0]
    if int(contagem) > 0:
        raise FalhaOperacionalErro(
            f"rotulos_fora_da_particao populacao={populacao.dataset_id} "
            f"rotulos={labels.dataset_id} divergentes={contagem}"
        )


def _consulta(
    dataset: DatasetRef, run: RunResult, particao: Particao
) -> tuple[str, dict[str, str]]:
    if dataset.schema_id == SCHEMA_AGREGADOS:
        metodo = run.metodo.value if run.metodo is not None else ""
        if not metodo:
            raise ValueError(f"execucao_sem_metodo run={run.run_id}")
        return (
            "SELECT $m AS metodo, row_id, resultado FROM read_parquet($c) WHERE run_id = $r",
            {"m": metodo, "c": dataset.caminho, "r": run.run_id},
        )
    return (
        (
            "SELECT metodo, row_id, resultado FROM read_parquet($c) "
            "WHERE run_id = $r AND particao = $p"
        ),
        {"c": dataset.caminho, "r": run.run_id, "p": particao.value},
    )


def ler_situacoes(
    con: duckdb.DuckDBPyConnection, runs: Sequence[RunResult], particao: Particao
) -> dict[str, dict[str, Situacao]]:
    """Situação por método e row_id, a partir de `agregados_registro.v1` ou das predições.

    Raises:
        ValueError: execução sem saída avaliável, método repetido ou resultado desconhecido.
    """
    situacoes: dict[str, dict[str, Situacao]] = {}
    for run in runs:
        da_execucao = _da_execucao(con, run, particao)
        if repetidos := sorted(set(da_execucao) & set(situacoes)):
            raise ValueError(f"metodo_repetido metodos={','.join(repetidos)}")
        situacoes.update(da_execucao)
    return situacoes


def _da_execucao(
    con: duckdb.DuckDBPyConnection, run: RunResult, particao: Particao
) -> dict[str, dict[str, Situacao]]:
    avaliaveis = {SCHEMA_AGREGADOS, SCHEMA_PREDICOES.schema_id}
    saidas = [ds for ds in run.saidas if ds.schema_id in avaliaveis]
    if not saidas:
        raise ValueError(f"execucao_sem_saida_avaliavel run={run.run_id}")
    situacoes: dict[str, dict[str, Situacao]] = {}
    if run.metodo is not None:
        situacoes[run.metodo.value] = {}
    for dataset in saidas:
        verificar_entrada(con, dataset)
        sql, parametros = _consulta(dataset, run, particao)
        for metodo, row_id, resultado in con.execute(sql, parametros).fetchall():
            if resultado not in _SITUACOES:
                raise ValueError(f"resultado_desconhecido run={run.run_id} valor={resultado}")
            situacoes.setdefault(str(metodo), {})[str(row_id)] = _SITUACOES[resultado]
    return situacoes
