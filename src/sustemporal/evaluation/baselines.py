"""Classificador histórico e controle trivial (T10)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa

from sustemporal.contracts.base import OrigemDados, hash_canonico
from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.experiment import (
    EstadoExecucao,
    ModoExecucao,
    Particao,
    RunResult,
    TipoExecucao,
)
from sustemporal.contracts.records import (
    ColunaCanonica,
    DatasetRef,
    EsquemaCanonico,
    PapelColuna,
    TipoCanonico,
    calcular_dataset_id,
)
from sustemporal.contracts.temporal import MetodoId
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.baselines_modelo import Ajuste, Linha, Predicao, ajustar, prever
from sustemporal.evaluation.features import OrigemAtributo, auditar_features
from sustemporal.gates import DIR_DECISOES, exigir_confirmatorio_valido
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.sia_pa import gravar_parquet, produtor
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo
from sustemporal.runtime_info import ambiente, versao_codigo

if TYPE_CHECKING:
    from collections.abc import Callable

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.experiment import FeatureSpec, SplitManifest

__all__ = ["SCHEMA_PREDICOES", "fit_baseline"]

logger = logging.getLogger(__name__)


def _coluna(nome: str, tipo: TipoCanonico, papel: PapelColuna) -> ColunaCanonica:
    return ColunaCanonica(nome=nome, tipo=tipo, papel=papel, anulavel=False)


SCHEMA_PREDICOES = EsquemaCanonico(
    schema_id="predicoes_baseline.v1",
    descricao=(
        "Predições do B_ML e do controle trivial por registro e partição; escore em [0, 1] com 9 "
        "casas e resultado ALERTA ou SEM_ALERTA. Sem rótulo nem campo de erro."
    ),
    chave=("run_id", "row_id", "metodo"),
    colunas=(
        _coluna("run_id", TipoCanonico.TEXTO, PapelColuna.CHAVE),
        _coluna("row_id", TipoCanonico.TEXTO, PapelColuna.CHAVE),
        _coluna("metodo", TipoCanonico.TEXTO, PapelColuna.CHAVE),
        _coluna("particao", TipoCanonico.TEXTO, PapelColuna.LINHAGEM),
        _coluna("escore", TipoCanonico.DECIMAL, PapelColuna.DIAGNOSTICO),
        _coluna("resultado", TipoCanonico.TEXTO, PapelColuna.DIAGNOSTICO),
    ),
)
_TIPOS_PREDICOES = pa.schema(
    [
        ("run_id", pa.string()),
        ("row_id", pa.string()),
        ("metodo", pa.string()),
        ("particao", pa.string()),
        ("escore", pa.decimal128(10, 9)),
        ("resultado", pa.string()),
    ]
)
_SCHEMA_ENTRADA = "sia_pa.v1"
_SCHEMA_ROTULOS = "sia_pa_rotulos.v1"


def _agora() -> datetime:
    return datetime.now(UTC)


def _particoes_permitidas(
    split: SplitManifest, modo: ModoExecucao
) -> tuple[dict[Particao, DatasetRef], dict[Particao, DatasetRef]]:
    """População e rótulos só das partições que o modo pode ler; TESTE só no confirmatório."""
    if split.particoes is None:
        raise ValueError(f"split_sem_particoes split={split.split_id}")
    if split.rotulos_por_particao is None:
        raise ValueError(f"baseline_sem_rotulos split={split.split_id}")
    permitidas = [Particao.DESENVOLVIMENTO, Particao.CALIBRACAO]
    if modo is ModoExecucao.CONFIRMATORIO:
        permitidas.append(Particao.TESTE)
    return (
        {p: split.particoes[p] for p in permitidas},
        {p: split.rotulos_por_particao[p] for p in permitidas},
    )


def _origem_unica(datasets: list[DatasetRef]) -> OrigemDados:
    origens = {dataset.origem_dados for dataset in datasets}
    if len(origens) != 1:
        raise ValueError(
            f"baseline_entradas_de_origens_distintas origens={','.join(sorted(origens))}"
        )
    return origens.pop()


def _verificar(con: duckdb.DuckDBPyConnection, dataset: DatasetRef, schema_id: str) -> None:
    if dataset.schema_id != schema_id:
        raise ValueError(
            f"baseline_schema_invalido esperado={schema_id} obtido={dataset.schema_id}"
        )
    try:
        verificar_conteudo(con, dataset)
    except (ConteudoDivergente, duckdb.Error) as erro:
        raise FalhaOperacionalErro(
            f"baseline_entrada_ilegivel_ou_divergente dataset={dataset.dataset_id} erro={erro}"
        ) from erro


def _carregar(
    con: duckdb.DuckDBPyConnection, dataset: DatasetRef, rotulos: DatasetRef, colunas: list[str]
) -> list[Linha]:
    permitidas = [c.nome for c in carregar_esquema(_SCHEMA_ENTRADA).colunas]
    projecao = ", ".join(f"p.{identificador_seguro(c, permitidas)}" for c in colunas)
    cursor = con.execute(
        f"SELECT p.row_id, {projecao}, r.rotulo FROM read_parquet($p) p "  # noqa: S608
        "LEFT JOIN read_parquet($r) r ON p.row_id = r.row_id ORDER BY p.row_id",
        {"p": dataset.caminho, "r": rotulos.caminho},
    )
    nomes = ["row_id", *colunas, "rotulo"]
    linhas = [dict(zip(nomes, valores, strict=True)) for valores in cursor.fetchall()]
    if len({linha["row_id"] for linha in linhas}) != len(linhas):
        raise ValueError(f"rotulos_com_row_id_repetido dataset={rotulos.dataset_id}")
    return linhas


def _gravar_predicoes(
    predicoes: list[Predicao],
    run_id: str,
    destino: Path,
    *,
    origem: OrigemDados,
    artefatos: tuple[str, ...],
) -> DatasetRef:
    colunas = [c.nome for c in SCHEMA_PREDICOES.colunas]
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        linhas = [(run_id, *linha) for linha in predicoes]
        arrow = pa.table(
            {
                campo.name: pa.array([linha[i] for linha in linhas], campo.type)
                for i, campo in enumerate(_TIPOS_PREDICOES)
            },
            schema=_TIPOS_PREDICOES,
        )
        con.register("predicoes_arrow", arrow)
        con.execute("CREATE TEMP TABLE predicoes AS SELECT * FROM predicoes_arrow")
        hash_logico = hash_logico_relacao(con, "predicoes", colunas)
        dataset_id = calcular_dataset_id(SCHEMA_PREDICOES.schema_id, hash_logico, artefatos)
        gravar_parquet(con, "predicoes", destino / f"{dataset_id}.parquet")
    finally:
        con.close()
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=SCHEMA_PREDICOES.schema_id,
        caminho=str(destino / f"{dataset_id}.parquet"),
        hash_logico=hash_logico,
        linhas=len(predicoes),
        artifact_ids=artefatos,
        origem_dados=origem,
        produzido_por=produtor("evaluation.baselines.fit_baseline"),
    )


def _run_id(
    config: RunConfig, split: SplitManifest, features: FeatureSpec, entradas: list[DatasetRef]
) -> str:
    """Identidade só das entradas lidas; o `split_id` cita rótulos de partições não lidas."""
    conteudo = {
        "config": config.config_hash,
        "spec": split.spec.model_dump(mode="json"),
        "features": features.model_dump(mode="json"),
        "entradas": [dataset.hash_logico for dataset in entradas],
    }
    return f"bml_{hash_canonico(conteudo)}"


def _ler_particoes(
    particoes: dict[Particao, DatasetRef],
    rotulos: dict[Particao, DatasetRef],
    colunas: list[str],
) -> dict[Particao, list[Linha]]:
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        for particao, dataset in particoes.items():
            _verificar(con, dataset, _SCHEMA_ENTRADA)
            _verificar(con, rotulos[particao], _SCHEMA_ROTULOS)
        return {p: _carregar(con, ds, rotulos[p], colunas) for p, ds in particoes.items()}
    finally:
        con.close()


def _gravar_saidas(
    ajuste: Ajuste,
    dados: dict[Particao, list[Linha]],
    origens: tuple[OrigemAtributo, ...],
    destino: Path,
    *,
    origem: OrigemDados,
    artefatos: tuple[str, ...],
) -> DatasetRef:
    destino.mkdir(parents=True, exist_ok=True)
    predicoes = prever(ajuste, dados)
    saida = _gravar_predicoes(predicoes, destino.name, destino, origem=origem, artefatos=artefatos)
    parametros = {**ajuste.parametros(), "atributos": [asdict(o) for o in origens]}
    texto = json.dumps(parametros, ensure_ascii=False, indent=2, sort_keys=True)
    (destino / "parametros.json").write_text(texto, encoding="utf-8")
    return saida


def _resultado(
    config: RunConfig,
    run_id: str,
    entradas: list[DatasetRef],
    saida: DatasetRef,
    *,
    origem: OrigemDados,
    inicio: datetime,
    fim: datetime,
) -> RunResult:
    raiz = Path.cwd()
    return RunResult(
        run_id=run_id,
        tipo=TipoExecucao.BASELINE_ML,
        metodo=MetodoId.B_ML,
        modo=config.modo,
        config_hash=config.config_hash,
        codigo=versao_codigo(raiz),
        ambiente=ambiente(raiz),
        semente=config.semente,
        entradas=tuple(entradas),
        saidas=(saida,),
        estado=EstadoExecucao.CONCLUIDA,
        iniciado_em=inicio,
        concluido_em=fim,
        freeze_id=config.freeze_id,
        origem_dados=origem,
    )


def fit_baseline(
    split: SplitManifest,
    features: FeatureSpec,
    config: RunConfig,
    out: Path,
    *,
    relogio: Callable[[], datetime] | None = None,
    decisoes: Path = DIR_DECISOES,
) -> RunResult:
    """Ajusta o baseline apenas com dados de treino e calibração.

    O exploratório lê só população e rótulos de DESENVOLVIMENTO e CALIBRACAO (rótulos já
    particionados no split); o TESTE só é lido no confirmatório liberado por G2. Codificação,
    frequências, balanceamento e coeficientes vêm do desenvolvimento; o limiar, da calibração.

    Raises:
        ValueError: sem rótulos, atributo proibido, esquema inesperado ou treino sem as duas
            classes.
        PortaoRecusado: confirmatório sem dados reais ou sem G2 para o congelamento.
        FalhaOperacionalErro: entrada ilegível ou diferente do `DatasetRef`.
    """
    agora = relogio or _agora
    iniciado = agora()
    particoes, rotulos = _particoes_permitidas(split, config.modo)
    entradas = [*particoes.values(), *rotulos.values()]
    origem = _origem_unica(entradas)
    exigir_confirmatorio_valido(config, origem, diretorio=decisoes)
    esquemas = [carregar_esquema(_SCHEMA_ENTRADA), carregar_esquema(_SCHEMA_ROTULOS)]
    origens = auditar_features(features, esquemas)
    if any(o.schema_id != _SCHEMA_ENTRADA for o in origens):
        raise ValueError(f"baseline_atributo_fora_do_esquema esperado={_SCHEMA_ENTRADA}")
    dados = _ler_particoes(particoes, rotulos, [o.coluna for o in origens])
    ajuste = ajustar(dados, features, config.semente)
    run_id = _run_id(config, split, features, entradas)
    artefatos = tuple(sorted({a for ds in particoes.values() for a in ds.artifact_ids}))
    destino = out / run_id
    saida = _gravar_saidas(ajuste, dados, origens, destino, origem=origem, artefatos=artefatos)
    run = _resultado(config, run_id, entradas, saida, origem=origem, inicio=iniciado, fim=agora())
    (destino / "run.json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
    logger.info("baseline_ajustado run=%s limiar=%s", run_id, ajuste.limiar)
    return run
