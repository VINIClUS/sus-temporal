"""Partições temporais da coorte (T10)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from sustemporal.config import load_config
from sustemporal.contracts.base import hash_canonico
from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.experiment import (
    CohortSpec,
    Particao,
    PertencaGeografica,
    SplitManifest,
    SplitSpec,
    Territorio,
)
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.sia_pa import gravar_parquet, produtor
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["CONFIG_PARTICOES", "SCHEMA_ENTRADA", "build_splits", "carregar_spec"]

logger = logging.getLogger(__name__)

CONFIG_PARTICOES = Path("config/splits.yaml")
SCHEMA_ENTRADA = "sia_pa.v1"
_TABELA = "populacao_split"
_LIMITES_FIXOS = (
    (
        "row_id_identifica_ocorrencia_no_arquivo: nao identifica paciente, tentativa nem "
        "reapresentacao"
    ),
    (
        "sem_vinculo_longitudinal: reapresentacoes nao vinculaveis entre competencias permanecem "
        "ocorrencias distintas; multiplicidades preservadas"
    ),
    (
        "dependencias_fora_da_fronteira: competencias auxiliares fora dos intervalos podem ser "
        "consultadas pelas regras, mas seus registros nao entram na populacao"
    ),
    (
        "particao_por_competencia_de_processamento: competencia_atendimento preservada em coluna "
        "propria e nunca usada para particionar"
    ),
)


def carregar_spec(caminho: Path = CONFIG_PARTICOES) -> SplitSpec:
    """Partições declaradas em `config/splits.yaml`.

    Raises:
        ValueError: configuração sem `particoes`.
    """
    spec = load_config(caminho).particoes
    if spec is None:
        raise ValueError(f"config_sem_particoes caminho={caminho}")
    return spec


def _municipios(cohort: CohortSpec) -> list[str]:
    if cohort.pertenca is PertencaGeografica.HISTORICA:
        raise ValueError(f"pertenca_historica_sem_historico_versionado coorte={cohort.cohort_id}")
    territorio = Territorio.model_validate(carregar_yaml(Path(cohort.territorio)))
    if territorio.uf != cohort.uf:
        raise ValueError(f"territorio_de_outra_uf coorte={cohort.cohort_id} uf={territorio.uf}")
    return sorted(m.ibge6 for m in territorio.municipios)


def _sql_classificacao(spec: SplitSpec, cohort: CohortSpec) -> tuple[str, dict[str, object]]:
    parametros: dict[str, object] = {"ini": str(cohort.inicio), "fim": str(cohort.fim)}
    casos = []
    for i, intervalo in enumerate(spec.intervalos):
        parametros[f"p{i}_ini"] = str(intervalo.inicio)
        parametros[f"p{i}_fim"] = str(intervalo.fim)
        casos.append(
            f"WHEN competencia_processamento BETWEEN $p{i}_ini AND $p{i}_fim "
            f"THEN '{intervalo.particao.value}'"
        )
    instrumentos = ""
    if cohort.instrumentos:
        parametros["instrumentos"] = list(cohort.instrumentos)
        instrumentos = (
            "WHEN instrumento IS NULL OR NOT list_contains($instrumentos, instrumento) "
            "THEN 'fora_dos_instrumentos' "
        )
    motivo = (
        "CASE WHEN deletado THEN 'registro_deletado' "
        "WHEN competencia_processamento IS NULL THEN 'sem_competencia_processamento' "
        "WHEN competencia_processamento NOT BETWEEN $ini AND $fim THEN 'fora_da_coorte' "
        "WHEN municipio_estabelecimento IS NULL THEN 'sem_municipio_estabelecimento' "
        "WHEN NOT list_contains($municipios, municipio_estabelecimento) "
        f"THEN 'fora_do_territorio' {instrumentos}ELSE NULL END"
    )
    particao = f"CASE {' '.join(casos)} ELSE NULL END"
    sql = (
        f"CREATE TEMP TABLE {_TABELA} AS SELECT *, {motivo} AS _motivo, "  # noqa: S608
        f"{particao} AS _particao FROM read_parquet($caminho)"
    )
    return sql, parametros


def _classificar(
    con: duckdb.DuckDBPyConnection,
    dataset: DatasetRef,
    spec: SplitSpec,
    cohort: CohortSpec,
    municipios: list[str],
) -> dict[str, int]:
    sql, parametros = _sql_classificacao(spec, cohort)
    con.execute(sql, {**parametros, "caminho": dataset.caminho, "municipios": municipios})
    con.execute(
        f"UPDATE {_TABELA} SET _motivo = 'fora_das_particoes' "  # noqa: S608
        "WHERE _motivo IS NULL AND _particao IS NULL"
    )
    linhas = con.execute(
        f"SELECT _motivo, count(*) FROM {_TABELA} WHERE _motivo IS NOT NULL "  # noqa: S608
        "GROUP BY _motivo ORDER BY _motivo"
    ).fetchall()
    return {str(motivo): int(n) for motivo, n in linhas}


def _exigir_fontes_numa_particao(
    con: duckdb.DuckDBPyConnection, fonte_por_artefato: Mapping[str, str]
) -> int:
    pares = con.execute(
        f"SELECT DISTINCT artifact_id, _particao FROM {_TABELA} "  # noqa: S608
        "WHERE _motivo IS NULL ORDER BY artifact_id, _particao"
    ).fetchall()
    particoes: dict[str, set[str]] = {}
    artefatos: dict[str, set[str]] = {}
    for artifact_id, particao in pares:
        fonte = fonte_por_artefato.get(str(artifact_id), str(artifact_id))
        particoes.setdefault(fonte, set()).add(str(particao))
        artefatos.setdefault(fonte, set()).add(str(artifact_id))
    for fonte, encontradas in sorted(particoes.items()):
        if len(encontradas) > 1:
            raise ValueError(
                f"republicacao_em_particoes_distintas fonte={fonte} "
                f"particoes={','.join(sorted(encontradas))}"
            )
    return sum(1 for versoes in artefatos.values() if len(versoes) > 1)


def _gravar_particao(
    con: duckdb.DuckDBPyConnection, particao: Particao, dataset: DatasetRef, out: Path
) -> DatasetRef:
    colunas = [c.nome for c in carregar_esquema(SCHEMA_ENTRADA).colunas]
    projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
    tabela = f"particao_{particao.value.lower()}"
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {tabela} AS SELECT {projecao} "  # noqa: S608
        f"FROM {_TABELA} WHERE _motivo IS NULL AND _particao = $p ORDER BY row_id",
        {"p": particao.value},
    )
    hash_logico = hash_logico_relacao(con, tabela, colunas)
    linhas = int(con.execute(f"SELECT count(*) FROM {tabela}").fetchall()[0][0])  # noqa: S608
    artefatos = tuple(
        str(linha[0])
        for linha in con.execute(
            f"SELECT DISTINCT artifact_id FROM {tabela} ORDER BY 1"  # noqa: S608
        ).fetchall()
    )
    dataset_id = calcular_dataset_id(SCHEMA_ENTRADA, hash_logico, artefatos)
    destino = out / f"{dataset_id}.parquet"
    gravar_parquet(con, tabela, destino)
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=SCHEMA_ENTRADA,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=artefatos,
        origem_dados=dataset.origem_dados,
        produzido_por=produtor("evaluation.split.build_splits"),
    )


def _limites(cohort: CohortSpec, agrupadas: int | None) -> tuple[str, ...]:
    extras = []
    if agrupadas is None:
        extras.append(
            "republicacoes_sem_chave_de_fonte: cada artefato tratado como fonte propria; versoes "
            "de uma mesma fonte nao sao reconhecidas como tal"
        )
    else:
        extras.append(
            f"republicacoes_agrupadas_por_fonte fontes_com_mais_de_uma_versao={agrupadas}: "
            "versoes da mesma fonte ficam na mesma particao e nao sao observacoes independentes"
        )
    if cohort.pertenca is PertencaGeografica.A_DEFINIR:
        extras.append("pertenca_a_definir: aplicada a lista versionada do territorio como fixa")
    return (*_LIMITES_FIXOS, *extras)


def _verificar_entrada(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> None:
    if dataset.schema_id != SCHEMA_ENTRADA:
        raise ValueError(f"split_schema_invalido schema={dataset.schema_id}")
    try:
        verificar_conteudo(con, dataset)
    except (ConteudoDivergente, duckdb.Error) as erro:
        raise FalhaOperacionalErro(
            f"split_entrada_ilegivel_ou_divergente dataset={dataset.dataset_id} erro={erro}"
        ) from erro


def _split_id(
    dataset: DatasetRef,
    cohort: CohortSpec,
    spec: SplitSpec,
    fontes: Mapping[str, str] | None,
    *,
    municipios: list[str],
    inspecionados: tuple[str, ...],
) -> str:
    conteudo = {
        "dataset": dataset.hash_logico,
        "coorte": cohort.model_dump(mode="json", exclude={"territorio"}),
        "municipios": municipios,
        "spec": spec.model_dump(mode="json"),
        "fontes": dict(sorted(fontes.items())) if fontes is not None else None,
        "inspecionados": list(inspecionados),
    }
    return f"spl_{hash_canonico(conteudo)}"


def _particionar(
    dataset: DatasetRef,
    spec: SplitSpec,
    cohort: CohortSpec,
    municipios: list[str],
    fontes: Mapping[str, str],
    *,
    out: Path,
) -> tuple[dict[str, int], int, dict[Particao, DatasetRef]]:
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        _verificar_entrada(con, dataset)
        exclusoes = _classificar(con, dataset, spec, cohort, municipios)
        agrupadas = _exigir_fontes_numa_particao(con, fontes)
        particoes = {
            p.particao: _gravar_particao(con, p.particao, dataset, out) for p in spec.intervalos
        }
    finally:
        con.close()
    return exclusoes, agrupadas, particoes


def build_splits(
    dataset: DatasetRef,
    cohort: CohortSpec,
    out: Path,
    *,
    spec: SplitSpec | None = None,
    fonte_por_artefato: Mapping[str, str] | None = None,
    inspecionados: Iterable[str] = (),
) -> SplitManifest:
    """Separa desenvolvimento, calibração e teste por competência de processamento.

    Registros fora da coorte, do território ou dos intervalos não entram na população, e a
    exclusão é contada por motivo. Versões de uma mesma fonte (`fonte_por_artefato`) ficam na
    mesma partição.

    Raises:
        FalhaOperacionalErro: entrada ilegível ou diferente do `DatasetRef`.
        ValueError: esquema inesperado, pertença histórica, republicação em partições
            distintas ou artefato de teste já inspecionado.
    """
    spec = spec if spec is not None else carregar_spec()
    vistos = tuple(sorted(set(inspecionados)))
    municipios = _municipios(cohort)
    out.mkdir(parents=True, exist_ok=True)
    exclusoes, agrupadas, particoes = _particionar(
        dataset, spec, cohort, municipios, fonte_por_artefato or {}, out=out
    )
    manifesto = SplitManifest(
        split_id=_split_id(
            dataset, cohort, spec, fonte_por_artefato, municipios=municipios, inspecionados=vistos
        ),
        spec=spec,
        dataset_hash=dataset.hash_logico,
        linhas_por_particao={p: ds.linhas for p, ds in particoes.items()},
        hash_por_particao={p: ds.hash_logico for p, ds in particoes.items()},
        artefatos_inspecionados=vistos,
        artefatos_teste=particoes[Particao.TESTE].artifact_ids,
        cohort_id=cohort.cohort_id,
        particoes=particoes,
        exclusoes=exclusoes,
        limites=_limites(cohort, agrupadas if fonte_por_artefato is not None else None),
    )
    (out / f"{manifesto.split_id}.json").write_text(manifesto.model_dump_json(indent=2))
    logger.info(
        "split_construido split=%s linhas=%s exclusoes=%s",
        manifesto.split_id,
        manifesto.linhas_por_particao,
        manifesto.exclusoes,
    )
    return manifesto
