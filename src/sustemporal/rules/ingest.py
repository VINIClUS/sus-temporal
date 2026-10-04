"""Insumos do `validate --ingest`: pasta `execucao_*` do ingest e registro temporal (T07).

A produção é a união de todos os `sia_pa.v1` (cada linha física preservada, sem deduplicar) no
território do piloto; cada esquema auxiliar exigido vira uma relação derivada com as linhas de todos
os artefatos (a seleção do T06 decide quais valem); a integridade por versão vem do registro.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import ManifestoCorrompido
from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.duck import identificador_seguro
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema, requisito_auxiliar
from sustemporal.rules.conteudo import verificar_conteudo
from sustemporal.rules.preparo import conferir_tipos_fisicos
from sustemporal.temporal.registry import RegistroTemporal
from sustemporal.temporal.selector import partes_esperadas_do_catalogo

if TYPE_CHECKING:
    import duckdb

    from sustemporal.contracts.artifacts import ArtifactVersion
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.rules import RuleSpec

__all__ = [
    "InsumosIngest",
    "carregar_registro",
    "integridade_do_registro",
    "ler_datasets",
    "preparar_insumos_ingest",
]

logger = logging.getLogger(__name__)

PRODUCAO = "sia_pa.v1"
COBERTURA = "cobertura.v1"
_UNIAO = "uniao_ingest"
_NAO_INTEGRAS = {
    estado
    for estado in EstadoIntegridade
    if estado not in {EstadoIntegridade.OK, EstadoIntegridade.NAO_VERIFICADO}
}


@dataclass(frozen=True)
class InsumosIngest:
    """Produção no território, auxiliares por esquema, cobertura e exclusões contadas."""

    producao: DatasetRef
    auxiliares: tuple[DatasetRef, ...]
    cobertura: DatasetRef | None
    exclusoes: dict[str, int]


def ler_datasets(pasta: Path) -> list[DatasetRef]:
    """Um `DatasetRef` por linha de `pasta/datasets.jsonl`.

    Raises:
        ConfigInvalida: arquivo ausente, ilegível ou com linha inválida.
    """
    caminho = pasta / "datasets.jsonl"
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
        return [DatasetRef.model_validate_json(linha) for linha in linhas if linha.strip()]
    except (OSError, ValidationError) as erro:
        raise ConfigInvalida(f"ingest_datasets_invalido caminho={caminho}") from erro


def carregar_registro(config: RunConfig) -> RegistroTemporal:
    """Registro temporal do manifesto de aquisição conferido (cadeia e âncora).

    Raises:
        ConfigInvalida: manifesto ausente, ilegível ou corrompido.
    """
    caminho = Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO
    if not caminho.is_file():
        raise ConfigInvalida(f"manifesto_ausente caminho={caminho}")
    try:
        return RegistroTemporal.de_manifesto(
            caminho, partes_esperadas=partes_esperadas_do_catalogo(config)
        )
    except (ManifestoCorrompido, OSError, ValueError) as erro:
        raise ConfigInvalida(f"manifesto_invalido caminho={caminho} erro={erro}") from erro


def _gravidade(estado: EstadoIntegridade) -> int:
    if estado in _NAO_INTEGRAS:
        return 2
    return 1 if estado is EstadoIntegridade.NAO_VERIFICADO else 0


def integridade_do_registro(registro: RegistroTemporal) -> dict[str, EstadoIntegridade]:
    """Integridade por versão: a da versão, piorada pelas observações dela.

    Quarentena observada prevalece; tentativa com bytes que não terminou em `OBTIDO` (falha de
    coleta) deixa a versão `NAO_VERIFICADO`, nunca `OK`.
    """
    estados = {artefato: versao.integridade for artefato, versao in registro.versoes.items()}
    for obs in registro.observacoes:
        atual = estados.get(obs.artifact_id or "")
        if atual is None:
            continue
        candidato = obs.integridade or atual
        if obs.resultado is not ResultadoTentativa.OBTIDO and candidato is EstadoIntegridade.OK:
            candidato = EstadoIntegridade.NAO_VERIFICADO
        if _gravidade(candidato) > _gravidade(atual):
            estados[str(obs.artifact_id)] = candidato
    return estados


def _chave_logica(versao: ArtifactVersion) -> str:
    chave = versao.chave
    return f"{chave.fonte}|{chave.uf}|{chave.competencia_arquivo}|{chave.parte}"


def _exigir_producao_coerente(
    producao: list[DatasetRef], registro: RegistroTemporal, config: RunConfig
) -> None:
    artefatos = sorted({a for ref in producao for a in ref.artifact_ids})
    por_chave: dict[str, set[str]] = defaultdict(set)
    for artefato in artefatos:
        versao = registro.versoes.get(artefato)
        if versao is None:
            raise ConfigInvalida(f"producao_fora_do_registro artefato={artefato}")
        por_chave[_chave_logica(versao)].add(artefato)
    for chave, versoes in sorted(por_chave.items()):
        if len(versoes) > 1:
            raise ConfigInvalida(
                f"producao_com_versoes_concorrentes chave={chave} artefatos={sorted(versoes)}"
            )
    corte = config.corte_observacao
    if corte is None:
        return
    for artefato in artefatos:
        if not any(
            o.artifact_id == artefato
            and o.resultado is ResultadoTentativa.OBTIDO
            and o.observado_em <= corte
            for o in registro.observacoes
        ):
            raise ConfigInvalida(f"producao_observada_apos_o_corte artefato={artefato}")


def _classificar(
    datasets: list[DatasetRef], regras: list[RuleSpec]
) -> tuple[list[DatasetRef], dict[str, list[DatasetRef]], DatasetRef | None]:
    origens = {ref.origem_dados for ref in datasets}
    if len(origens) > 1:
        raise ConfigInvalida(f"ingest_com_origens_diferentes origens={sorted(map(str, origens))}")
    producao = [ref for ref in datasets if ref.schema_id == PRODUCAO]
    if not producao:
        raise ConfigInvalida("ingest_sem_producao schema=sia_pa.v1")
    coberturas = [ref for ref in datasets if ref.schema_id == COBERTURA]
    if len(coberturas) > 1:
        raise ConfigInvalida(f"ingest_com_varias_coberturas quantidade={len(coberturas)}")
    exigidos = sorted({requisito_auxiliar(regra).schema_id for regra in regras})
    auxiliares = {s: [ref for ref in datasets if ref.schema_id == s] for s in exigidos}
    return producao, auxiliares, coberturas[0] if coberturas else None


def _unir(con: duckdb.DuckDBPyConnection, refs: list[DatasetRef], schema_id: str) -> list[str]:
    """Tabela `_UNIAO` com todas as linhas físicas dos conjuntos conferidos (sem deduplicar)."""
    fisicas: set[str] = set()
    for ref in refs:
        verificar_conteudo(con, ref)
        fisicas |= conferir_tipos_fisicos(con, ref)
    colunas = [c.nome for c in carregar_esquema(schema_id).colunas if c.nome in fisicas]
    projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {_UNIAO} AS SELECT {projecao} "  # noqa: S608
        "FROM read_parquet($c, union_by_name = true)",
        {"c": [ref.caminho for ref in refs]},
    )
    return colunas


def _gravar(
    con: duckdb.DuckDBPyConnection,
    colunas: list[str],
    refs: list[DatasetRef],
    destino: Path,
) -> DatasetRef:
    schema_id = refs[0].schema_id
    artefatos = tuple(sorted({a for ref in refs for a in ref.artifact_ids}))
    hash_logico = hash_logico_relacao(con, _UNIAO, colunas)
    dataset_id = calcular_dataset_id(schema_id, hash_logico, artefatos)
    caminho = destino / f"{dataset_id}.parquet"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
    con.sql(f"SELECT {projecao} FROM {_UNIAO}").write_parquet(str(caminho))  # noqa: S608
    linhas = int(con.execute(f"SELECT count(*) FROM {_UNIAO}").fetchall()[0][0])  # noqa: S608
    logger.info("insumo_derivado schema=%s dataset=%s linhas=%d", schema_id, dataset_id, linhas)
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=schema_id,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=artefatos,
        origem_dados=refs[0].origem_dados,
        produzido_por="validate_ingest",
    )


def _recortar_territorio(
    con: duckdb.DuckDBPyConnection, colunas: list[str], municipios: frozenset[str]
) -> dict[str, int]:
    """Mantém só o território; conta as excluídas por motivo (nunca somem em silêncio)."""
    tem_municipio = "municipio_estabelecimento" in colunas
    coluna = "municipio_estabelecimento" if tem_municipio else "NULL"
    contagem = con.execute(
        f"SELECT count(*) FILTER (WHERE {coluna} IS NULL), "  # noqa: S608
        f"count(*) FILTER (WHERE {coluna} IS NOT NULL AND NOT list_contains($m, {coluna})) "
        f"FROM {_UNIAO}",
        {"m": sorted(municipios)},
    ).fetchall()[0]
    con.execute(
        f"DELETE FROM {_UNIAO} WHERE {coluna} IS NULL OR NOT list_contains($m, {coluna})",  # noqa: S608
        {"m": sorted(municipios)},
    )
    motivos = {"municipio_estabelecimento_ausente": contagem[0], "fora_do_territorio": contagem[1]}
    return {motivo: int(n) for motivo, n in motivos.items() if n}


def _exigir_row_id_unico(con: duckdb.DuckDBPyConnection) -> None:
    repetidos = con.execute(
        f"SELECT count(*) FROM (SELECT row_id FROM {_UNIAO} "  # noqa: S608
        "GROUP BY row_id HAVING count(*) > 1)"
    ).fetchall()[0][0]
    if repetidos:
        raise FalhaOperacionalErro(f"producao_com_row_id_repetido chaves={repetidos}")


def preparar_insumos_ingest(
    con: duckdb.DuckDBPyConnection,
    datasets: list[DatasetRef],
    regras: list[RuleSpec],
    contexto: tuple[RunConfig, RegistroTemporal, frozenset[str]],
    destino: Path,
) -> InsumosIngest:
    """Confere os conjuntos do ingest e grava as relações derivadas em `destino`.

    Raises:
        ConfigInvalida: origens diferentes, sem produção, várias coberturas, versões concorrentes,
            artefato fora do registro ou observado só depois do corte.
        FalhaOperacionalErro: `row_id` repetido na união da produção.
        ValueError: conteúdo ou tipo físico divergente do `DatasetRef`.
    """
    config, registro, municipios = contexto
    producao, auxiliares, cobertura = _classificar(datasets, regras)
    _exigir_producao_coerente(producao, registro, config)
    colunas = _unir(con, producao, PRODUCAO)
    _exigir_row_id_unico(con)
    exclusoes = _recortar_territorio(con, colunas, municipios)
    ref_producao = _gravar(con, colunas, producao, destino)
    derivados = [
        _gravar(con, _unir(con, refs, refs[0].schema_id), refs, destino)
        for refs in auxiliares.values()
        if refs
    ]
    if cobertura is not None:
        verificar_conteudo(con, cobertura)
    logger.info(
        "insumos_ingest_prontos producao=%s exclusoes=%s", ref_producao.dataset_id, exclusoes
    )
    return InsumosIngest(ref_producao, tuple(derivados), cobertura, exclusoes)
