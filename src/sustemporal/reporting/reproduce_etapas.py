"""Etapas do fluxo pequeno que a reprodução refaz: janelas do ingest, rótulos e partições (T14).

O `validate --ingest` exige que a produção da pasta do ingest seja toda do recorte do piloto, e o
protocolo avalia partições (DESENVOLVIMENTO, CALIBRACAO e TESTE) de uma série maior. A janela é a
pasta do ingest com só o SIA-PA dos arquivos das competências pedidas: o `validate` sobre ela lê a
mesma população da partição (o hash lógico confere, e `reproduce` o compara). Não há comando de CLI
para estas etapas; elas valem para o fluxo pequeno e para o que o `freeze` consome em
`<raiz_saidas>/split` (pendência T11 #27).
"""

from __future__ import annotations

import json
import logging
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow.parquet as pq

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro
from sustemporal.evaluation.freeze_entrada import campos_divergentes
from sustemporal.evaluation.labels import CODEBOOK_PA, label_pa
from sustemporal.evaluation.split import SCHEMA_ENTRADA, build_splits
from sustemporal.execucoes import raiz_execucoes
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.sia_pa import gravar_parquet, produtor
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.entrada import EntradaValidacao
from sustemporal.rules.ingest import ler_datasets
from sustemporal.rules.insumos import METODOS_DE_VALIDACAO
from sustemporal.rules.validate_ingest import validar_ingest

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.experiment import RunResult, SplitManifest, SplitSpec
    from sustemporal.contracts.temporal import MetodoId

__all__ = [
    "Derivado",
    "competencias_da_particao",
    "derivar_protocolo",
    "entradas_congeladas",
    "estados_do_ingest",
    "janela_do_ingest",
    "validar_janela",
]

logger = logging.getLogger(__name__)

_UNIAO = "uniao_sia_pa"
_NORMALIZADO = "NORMALIZADO"


@dataclass(frozen=True)
class Derivado:
    """União dos `sia_pa.v1` do ingest, os rótulos dela e o split que as partições formam."""

    uniao: DatasetRef
    rotulos: DatasetRef
    split: SplitManifest


def _manifesto(config: RunConfig) -> Manifesto:
    return Manifesto(Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO)


def _competencias_do_dataset(
    ref: DatasetRef, competencia_por_artefato: Mapping[str, str]
) -> set[str]:
    faltantes = [a for a in ref.artifact_ids if a not in competencia_por_artefato]
    if faltantes:
        raise ConfigInvalida(f"janela_artefato_fora_do_manifesto artefato={faltantes[0]}")
    return {competencia_por_artefato[a] for a in ref.artifact_ids}


def _na_janela(
    ref: DatasetRef, competencia_por_artefato: Mapping[str, str], pedidas: set[str]
) -> bool:
    if ref.schema_id != SCHEMA_ENTRADA:
        return True
    do_dataset = _competencias_do_dataset(ref, competencia_por_artefato)
    if do_dataset <= pedidas:
        return True
    if do_dataset & pedidas:
        raise ConfigInvalida(f"janela_com_dataset_misto dataset={ref.dataset_id}")
    return False


def janela_do_ingest(
    config: RunConfig, pasta: Path, destino: Path, competencias: Collection[str]
) -> Path:
    """Pasta com o `datasets.jsonl` do ingest sem o SIA-PA dos arquivos de fora da janela.

    Os conjuntos que não são SIA-PA (CNES, SIGTAP, cobertura) ficam todos: as regras buscam as
    competências de que precisam e a falta delas segue inconclusiva. A janela é por competência do
    arquivo, a mesma que `validate --ingest` confere contra o piloto.

    Raises:
        ConfigInvalida: ingest ilegível, artefato fora do manifesto ou conjunto SIA-PA com
            arquivos de janelas diferentes.
    """
    pedidas = {str(c) for c in competencias}
    versoes = _manifesto(config).ler().versoes
    competencia_por_artefato = {
        a: str(v.chave.competencia_arquivo)
        for a, v in versoes.items()
        if v.chave.competencia_arquivo
    }
    refs = [
        ref for ref in ler_datasets(pasta) if _na_janela(ref, competencia_por_artefato, pedidas)
    ]
    linhas = [ref.model_dump_json() for ref in refs]
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "datasets.jsonl").write_text("".join(f"{linha}\n" for linha in linhas), "utf-8")
    logger.info("janela_do_ingest destino=%s competencias=%s", destino, sorted(pedidas))
    return destino


def competencias_da_particao(particao: DatasetRef) -> tuple[str, ...]:
    """Competências de processamento (distintas, em ordem) das linhas da partição."""
    tabela = pq.read_table(particao.caminho, columns=["competencia_processamento"])
    valores = {str(v) for v in tabela.column(0).to_pylist() if v is not None}
    return tuple(sorted(valores))


def _unir_sia_pa(refs: list[DatasetRef], destino: Path, config: RunConfig) -> DatasetRef:
    colunas = [c.nome for c in carregar_esquema(SCHEMA_ENTRADA).colunas]
    projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
    origens = {ref.origem_dados for ref in refs}
    if len(origens) > 1:
        raise ConfigInvalida(f"ingest_com_origens_diferentes origens={sorted(map(str, origens))}")
    with closing(conectar(config.runtime)) as con:
        con.execute(
            f"CREATE TEMP TABLE {_UNIAO} AS SELECT {projecao} "  # noqa: S608
            "FROM read_parquet($c, union_by_name = true) ORDER BY row_id",
            {"c": [ref.caminho for ref in refs]},
        )
        hash_logico = hash_logico_relacao(con, _UNIAO, colunas)
        linhas = int(con.execute(f"SELECT count(*) FROM {_UNIAO}").fetchall()[0][0])  # noqa: S608
        artefatos = tuple(sorted({a for ref in refs for a in ref.artifact_ids}))
        dataset_id = calcular_dataset_id(SCHEMA_ENTRADA, hash_logico, artefatos)
        destino.mkdir(parents=True, exist_ok=True)
        arquivo = destino / f"{dataset_id}.parquet"
        gravar_parquet(con, _UNIAO, arquivo)
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=SCHEMA_ENTRADA,
        caminho=str(arquivo),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=artefatos,
        origem_dados=origens.pop(),
        produzido_por=produtor("reporting.reproduce_etapas.derivar_protocolo"),
    )


def _fonte_por_artefato(config: RunConfig) -> dict[str, str]:
    """Fonte lógica de cada versão (família, UF, competência do arquivo e parte).

    As versões de uma mesma fonte (republicações) ficam na mesma partição do split.
    """
    versoes = _manifesto(config).ler().versoes
    return {
        artefato: "|".join(
            str(valor)
            for valor in (v.chave.fonte, v.chave.uf, v.chave.competencia_arquivo, v.chave.parte)
        )
        for artefato, v in versoes.items()
    }


def derivar_protocolo(
    config: RunConfig,
    pasta: Path,
    destino: Path,
    *,
    spec: SplitSpec,
    inspecionados: Iterable[str] = (),
) -> Derivado:
    """União do SIA-PA do ingest, rótulos pelo codebook e partições do split, em `destino`.

    O split sai direto em `destino` (`spl_*.json`, `<split_id>.entradas.json` e as partições),
    onde o `freeze` e o `evaluate` o procuram (`<raiz_saidas>/split`). Os `inspecionados` são os
    artefatos já vistos no desenvolvimento: entram no `split_id` e não podem estar no TESTE.

    Raises:
        ConfigInvalida: config sem `coorte`, ingest sem SIA-PA ou com origens misturadas.
        ValueError: artefato inspecionado sem fonte no manifesto ou que cairia no TESTE.
    """
    if config.coorte is None:
        raise ConfigInvalida("derivar_protocolo_exige_coorte")
    producao = [ref for ref in ler_datasets(pasta) if ref.schema_id == SCHEMA_ENTRADA]
    if not producao:
        raise ConfigInvalida("ingest_sem_producao schema=sia_pa.v1")
    uniao = _unir_sia_pa(producao, destino / "entradas", config)
    (destino / "rotulos").mkdir(parents=True, exist_ok=True)
    rotulos = label_pa(uniao, CODEBOOK_PA, destino / "rotulos", runtime=config.runtime)
    split = build_splits(
        uniao,
        config.coorte,
        destino,
        spec=spec,
        fonte_por_artefato=_fonte_por_artefato(config),
        inspecionados=inspecionados,
        rotulos=rotulos,
    )
    return Derivado(uniao, rotulos, split)


def validar_janela(
    config: RunConfig, janela: Path, metodos: Collection[MetodoId] = METODOS_DE_VALIDACAO
) -> dict[MetodoId, RunResult]:
    """`validate --ingest` da janela, um método por vez, gravado em `raiz_execucoes(config)`.

    Raises:
        ConfigInvalida: catálogo, política, manifesto, território ou pasta inválidos.
    """
    saida = raiz_execucoes(config)
    return {metodo: validar_ingest(janela, metodo, config, saida) for metodo in metodos}


def estados_do_ingest(pasta: Path) -> dict[str, str]:
    """Estado de cada artefato no `resultados.jsonl` do ingest (`NORMALIZADO`, `ARQUIVOAUSENTE`).

    O artefato com mais de um resultado (o SIGTAP grava um por tabela) só é `NORMALIZADO` se todos
    forem; o primeiro estado de falha prevalece.

    Raises:
        FalhaOperacionalErro: `resultados.jsonl` ausente, ilegível ou fora do formato.
    """
    caminho = pasta / "resultados.jsonl"
    try:
        texto = caminho.read_text(encoding="utf-8")
        resultados = [json.loads(linha) for linha in texto.splitlines() if linha.strip()]
        pares = [(str(r["artifact_id"]), str(r["estado"])) for r in resultados]
    except (OSError, ValueError, KeyError, TypeError) as erro:
        raise FalhaOperacionalErro(
            f"ingest_ilegivel caminho={caminho} erro={type(erro).__name__}"
        ) from erro
    estados: dict[str, str] = {}
    for artefato, estado in pares:
        if estados.get(artefato, _NORMALIZADO) == _NORMALIZADO:
            estados[artefato] = estado
    return estados


def _ler_entrada(caminho: Path) -> EntradaValidacao | None:
    try:
        return EntradaValidacao.model_validate_json(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _confere(identidades: Mapping[str, str], entrada: EntradaValidacao) -> bool:
    divergentes = campos_divergentes(identidades, entrada)
    return all(campo == "politica" and entrada.politica is None for campo in divergentes)


def entradas_congeladas(
    pasta: Path, identidades: Mapping[str, Mapping[str, str]]
) -> dict[str, EntradaValidacao]:
    """`pasta/<politica_id>.json` de cada política congelada, se for a entrada congelada.

    O manifesto guarda só a identidade de cada campo; a entrada original (a que o `freeze` leu em
    `split/insumos`) dá os artefatos dos auxiliares. Entra só a que existe, é legível e tem, campo a
    campo, a identidade congelada; a ausente, a ilegível e a alterada depois do congelamento ficam
    de fora. A política resolvida que a entrada não traz vale a do catálogo congelado, como no
    `freeze`.
    """
    entradas = {}
    for politica_id in sorted(identidades):
        entrada = _ler_entrada(pasta / f"{politica_id}.json")
        if entrada is not None and _confere(identidades[politica_id], entrada):
            entradas[politica_id] = entrada
        else:
            logger.warning("insumo_original_nao_conferido politica=%s pasta=%s", politica_id, pasta)
    return entradas
