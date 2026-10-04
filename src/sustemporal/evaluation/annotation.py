"""Amostra estratificada para avaliação humana cega (T12).

A população são as rejeições observadas (rótulo NAO_APROVADO) da partição de teste; os estratos
usam só características observáveis independentes do método. Nenhuma saída do motor é lida: a
seleção não depende de o motor explicar a rejeição. O treino dos avaliadores sai da partição de
desenvolvimento e fica fora da avaliação final.
"""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts import (
    AnnotationSample,
    Estrato,
    Particao,
    RuntimeConfig,
    hash_canonico,
)
from sustemporal.duck import conectar
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro
from sustemporal.evaluation.annotation_amostragem import alocar, embaralhar, estratos, sortear
from sustemporal.evaluation.annotation_pacote import (
    COLUNAS_PACOTE,
    FORMULARIO,
    FORMULARIO_VERSAO,
    carregar_mapa,
    casos_do_pacote,
    gravar_saidas,
)
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, RunConfig, SplitManifest

__all__ = [
    "COLUNAS_PACOTE",
    "DIMENSOES_OBSERVAVEIS",
    "FORMULARIO",
    "FORMULARIO_VERSAO",
    "SCHEMA_REGISTROS",
    "SCHEMA_ROTULOS",
    "carregar_mapa",
    "prepare_annotation_sample",
]

logger = logging.getLogger(__name__)

DIMENSOES_OBSERVAVEIS = ("instrumento", "periodo", "estabelecimento", "defasagem")
SCHEMA_REGISTROS = "sia_pa.v1"
SCHEMA_ROTULOS = "sia_pa_rotulos.v1"
REJEICAO = "NAO_APROVADO"
_MESES = "TRY_CAST(substr({c}, 1, 4) AS INTEGER) * 12 + TRY_CAST(substr({c}, 5, 2) AS INTEGER)"
_SQL_REJEICOES = (
    "WITH base AS (SELECT p.row_id, p.cnes, p.instrumento, p.competencia_processamento, "  # noqa: S608
    "r.rotulo, ("
    + _MESES.format(c="p.competencia_processamento")
    + ") - ("
    + _MESES.format(c="p.competencia_atendimento")
    + ") AS d FROM read_parquet($registros) p LEFT JOIN read_parquet($rotulos) r USING (row_id)), "
    "volume AS (SELECT cnes, ntile(3) OVER (ORDER BY n, cnes) AS faixa FROM "
    "(SELECT cnes, count(*) AS n FROM base WHERE cnes IS NOT NULL GROUP BY cnes)) "
    "SELECT row_id, rotulo, {partes} AS estrato FROM base LEFT JOIN volume USING (cnes) "
    "ORDER BY row_id"
)
_SQL_DIMENSAO = {
    "instrumento": "coalesce(instrumento, 'DESCONHECIDO')",
    "periodo": "coalesce(substr(competencia_processamento, 1, 4), 'DESCONHECIDO')",
    "estabelecimento": (
        "CASE WHEN cnes IS NULL THEN 'DESCONHECIDO' ELSE 'VOLUME_' || CAST(faixa AS VARCHAR) END"
    ),
    "defasagem": (
        "CASE WHEN d IS NULL THEN 'DESCONHECIDA' WHEN d < 0 THEN 'NEGATIVA' "
        "WHEN d = 0 THEN '0' WHEN d = 1 THEN '1' WHEN d <= 3 THEN '2_3' ELSE '4_MAIS' END"
    ),
}


def _exigir_dimensoes(dimensoes: tuple[str, ...]) -> None:
    invalidas = [d for d in dimensoes if d not in DIMENSOES_OBSERVAVEIS]
    if invalidas or not dimensoes or len(set(dimensoes)) != len(dimensoes):
        raise ValueError(f"dimensao_nao_observavel dimensoes={','.join(dimensoes)}")


def _particao(
    split: SplitManifest, particoes: Mapping[Particao, DatasetRef] | None, particao: Particao
) -> DatasetRef:
    fonte = particoes if particoes is not None else getattr(split, "particoes", None)
    dataset = fonte.get(particao) if fonte is not None else None
    if dataset is None:
        raise ConfigInvalida(f"anotacao_sem_particao particao={particao} split={split.split_id}")
    esperado = (split.hash_por_particao.get(particao), split.linhas_por_particao.get(particao))
    if dataset.schema_id != SCHEMA_REGISTROS or (dataset.hash_logico, dataset.linhas) != esperado:
        raise ValueError(
            f"particao_diverge_do_split particao={particao} dataset={dataset.dataset_id}"
        )
    return dataset


def _exigir_origem(config: RunConfig, *datasets: DatasetRef) -> None:
    origens = {d.origem_dados for d in datasets}
    if config.origem_dados is not None:
        origens.add(config.origem_dados)
    if len(origens) != 1:
        raise ValueError(f"origem_dados_divergente origens={','.join(sorted(origens))}")


def _conferir(con: duckdb.DuckDBPyConnection, *datasets: DatasetRef) -> None:
    for dataset in datasets:
        try:
            verificar_conteudo(con, dataset)
        except (ConteudoDivergente, duckdb.Error) as erro:
            raise FalhaOperacionalErro(
                f"anotacao_entrada_ilegivel_ou_divergente dataset={dataset.dataset_id} erro={erro}"
            ) from erro


def _unicidade(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    repetidos = con.execute(
        "SELECT count(*) - count(DISTINCT row_id) FROM read_parquet($c)", {"c": dataset.caminho}
    ).fetchall()[0][0]
    if repetidos:
        raise ValueError(f"row_id_repetido dataset={dataset.dataset_id} repetidos={repetidos}")


def _rejeicoes(
    con: duckdb.DuckDBPyConnection,
    registros: DatasetRef,
    labels: DatasetRef,
    dimensoes: tuple[str, ...],
) -> dict[str, str]:
    """row_id → estrato das rejeições da partição; falha se algum registro não tem rótulo."""
    partes = " || '|' || ".join(f"'{d}=' || {_SQL_DIMENSAO[d]}" for d in dimensoes)
    sql = _SQL_REJEICOES.format(partes=partes)
    linhas = con.execute(
        sql, {"registros": registros.caminho, "rotulos": labels.caminho}
    ).fetchall()
    sem_rotulo = sum(1 for _, rotulo, _ in linhas if rotulo is None)
    if sem_rotulo:
        raise ValueError(
            f"rotulos_nao_cobrem_particao dataset={registros.dataset_id} faltantes={sem_rotulo}"
        )
    return {str(row_id): str(estrato) for row_id, rotulo, estrato in linhas if rotulo == REJEICAO}


def _sortear_final(
    populacao: Mapping[str, str], tamanho: int, semente: int
) -> tuple[dict[str, int], dict[str, int], list[str]]:
    membros: dict[str, list[str]] = {}
    for row_id, estrato in populacao.items():
        membros.setdefault(estrato, []).append(row_id)
    contagens = {estrato: len(ids) for estrato, ids in membros.items()}
    alocacao = alocar(contagens, tamanho)
    sorteados = sortear(membros, alocacao, semente)
    return contagens, alocacao, sorted(r for ids in sorteados.values() for r in ids)


def _colunas_excluidas(con: duckdb.DuckDBPyConnection, registros: DatasetRef) -> tuple[str, ...]:
    descricao = con.execute(
        "DESCRIBE SELECT * FROM read_parquet($c)", {"c": registros.caminho}
    ).fetchall()
    fisicas = {str(linha[0]) for linha in descricao}
    canonicas = {c.nome for c in carregar_esquema(SCHEMA_REGISTROS).colunas}
    rotulos = {c.nome for c in carregar_esquema(SCHEMA_ROTULOS).colunas} - {"row_id", "rotulo"}
    return tuple(sorted((fisicas | canonicas | rotulos) - set(COLUNAS_PACOTE)))


def _treino(populacao: Mapping[str, str], tamanho: int, semente: int) -> list[str]:
    candidatos = embaralhar(list(populacao), semente, "treino")
    return sorted(candidatos[:tamanho])


def _ordem(row_ids: list[str], semente: int, prefixo: str) -> list[tuple[str, str]]:
    return [
        (f"{prefixo}_{i:04d}", row_id)
        for i, row_id in enumerate(embaralhar(row_ids, semente, prefixo), start=1)
    ]


@dataclass(frozen=True)
class _Sorteio:
    populacao: dict[str, str]
    estratos: tuple[Estrato, ...]
    casos: list[str]
    treino: list[str]
    pacotes: dict[str, list[dict[str, object]]]
    mapa: dict[str, str]
    excluidas: tuple[str, ...]


def _sortear(
    con: duckdb.DuckDBPyConnection,
    labels: DatasetRef,
    teste: DatasetRef,
    desenvolvimento: DatasetRef,
    parametros: tuple[tuple[str, ...], int, int, int],
) -> _Sorteio:
    dimensoes, tamanho, tamanho_treino, semente = parametros
    _conferir(con, labels, teste, desenvolvimento)
    for dataset in (labels, teste, desenvolvimento):
        _unicidade(con, dataset)
    populacao = _rejeicoes(con, teste, labels, dimensoes)
    contagens, alocacao, casos = _sortear_final(populacao, tamanho, semente)
    treino = _treino(_rejeicoes(con, desenvolvimento, labels, dimensoes), tamanho_treino, semente)
    ordem_casos = _ordem(casos, semente, "caso")
    ordem_treino = _ordem(treino, semente, "treino")
    return _Sorteio(
        populacao=populacao,
        estratos=estratos(contagens, alocacao),
        casos=casos,
        treino=treino,
        pacotes={
            "casos": casos_do_pacote(con, teste, labels, ordem_casos),
            "treino": casos_do_pacote(con, desenvolvimento, labels, ordem_treino),
        },
        mapa=dict(ordem_casos + ordem_treino),
        excluidas=_colunas_excluidas(con, teste),
    )


def _montar_amostra(
    sorteio: _Sorteio, config: RunConfig, dimensoes: tuple[str, ...], datasets: list[str]
) -> AnnotationSample:
    campos: dict[str, object] = {
        "freeze_id": config.freeze_id,
        "semente": config.semente,
        "casos": sorteio.casos,
        "casos_treino": sorteio.treino,
        "colunas_excluidas": list(sorteio.excluidas),
        "formulario_versao": FORMULARIO_VERSAO,
        "dimensoes_estrato": list(dimensoes),
    }
    estratos_json = [e.model_dump(mode="json") for e in sorteio.estratos]
    identidade = {**campos, "estratos": estratos_json, "datasets": datasets}
    return AnnotationSample.model_validate(
        {**campos, "estratos": sorteio.estratos, "sample_id": f"ann_{hash_canonico(identidade)}"}
    )


def prepare_annotation_sample(
    labels: DatasetRef,
    split: SplitManifest,
    config: RunConfig,
    out: Path,
    *,
    particoes: Mapping[Particao, DatasetRef] | None = None,
    tamanho: int = 400,
    tamanho_treino: int = 20,
    dimensoes: tuple[str, ...] = DIMENSOES_OBSERVAVEIS,
) -> AnnotationSample:
    """Sorteia a amostra estratificada e prepara pacotes sem saídas do motor.

    Raises:
        ConfigInvalida: partição de teste ou de desenvolvimento não materializada.
        FalhaOperacionalErro: Parquet ilegível ou diferente do `DatasetRef`.
        ValueError: dimensão não observável, partição divergente do split, rótulos que não
            cobrem a partição, origem de dados divergente ou mais estratos que casos.
    """
    _exigir_dimensoes(dimensoes)
    if tamanho_treino < 0:
        raise ValueError(f"tamanho_treino_invalido tamanho={tamanho_treino}")
    if labels.schema_id != SCHEMA_ROTULOS:
        raise ValueError(f"rotulos_schema_invalido schema={labels.schema_id}")
    teste = _particao(split, particoes, Particao.TESTE)
    desenvolvimento = _particao(split, particoes, Particao.DESENVOLVIMENTO)
    _exigir_origem(config, labels, teste, desenvolvimento)
    parametros = (dimensoes, tamanho, tamanho_treino, config.semente)
    with closing(conectar(RuntimeConfig(duckdb_threads=1))) as con:
        sorteio = _sortear(con, labels, teste, desenvolvimento, parametros)
    datasets = [labels.dataset_id, teste.dataset_id, desenvolvimento.dataset_id]
    amostra = _montar_amostra(sorteio, config, dimensoes, datasets)
    gravar_saidas(out, amostra, sorteio.pacotes, sorteio.mapa, sorteio.populacao)
    logger.info(
        "amostra_anotacao amostra=%s rejeicoes=%d estratos=%d casos=%d treino=%d",
        amostra.sample_id,
        len(sorteio.populacao),
        len(amostra.estratos),
        len(amostra.casos),
        len(amostra.casos_treino),
    )
    return amostra
