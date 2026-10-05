"""Insumos do `validate --ingest`: pasta `execucao_*` do ingest e registro temporal (T07).

A produção é a união de todos os `sia_pa.v1` (cada linha física preservada, sem deduplicar) no
território do piloto; cada esquema auxiliar exigido vira uma relação derivada com as linhas de todos
os artefatos (a seleção do T06 decide quais valem); a integridade por versão vem do registro.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
from pydantic import ValidationError

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import ManifestoCorrompido
from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.duck import identificador_seguro
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.coverage import build_coverage
from sustemporal.rules.catalog import carregar_esquema, requisito_auxiliar
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo
from sustemporal.rules.ingest_conformidade import exigir_colunas_obrigatorias
from sustemporal.rules.ingest_selecao import exigir_versao_selecionavel, marcas_de_incompletude
from sustemporal.rules.preparo import conferir_tipos_fisicos
from sustemporal.temporal.registry import RegistroTemporal
from sustemporal.temporal.selector import partes_esperadas_do_catalogo

if TYPE_CHECKING:
    from datetime import datetime

    from sustemporal.contracts.artifacts import ArtifactVersion
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import SelecaoVersao

__all__ = [
    "InsumosIngest",
    "carregar_registro",
    "exigir_sem_deletados",
    "incompletude_da_cobertura",
    "integridade_do_registro",
    "ler_datasets",
    "preparar_insumos_ingest",
]

logger = logging.getLogger(__name__)

PRODUCAO = "sia_pa.v1"
COBERTURA = "cobertura.v1"
_UNIAO = "uniao_ingest"
_EXCLUSOES = (
    ("registro_deletado", "deletado IS TRUE"),
    ("sem_competencia_processamento", "competencia_processamento IS NULL"),
    ("fora_das_competencias_do_piloto", "NOT list_contains($c, competencia_processamento)"),
    ("territorio_indeterminado", "municipio_estabelecimento IS NULL"),
    ("fora_do_territorio", "NOT list_contains($m, municipio_estabelecimento)"),
)
_MARCA_INCOMPLETO = re.compile(r"sia_pa_incompleto competencia=([0-9]{6}) motivo=(.*?)(?:; |$)")
_NAO_INTEGRAS = {
    estado
    for estado in EstadoIntegridade
    if estado not in {EstadoIntegridade.OK, EstadoIntegridade.NAO_VERIFICADO}
}


@dataclass(frozen=True)
class InsumosIngest:
    """Produção no território, auxiliares por esquema, cobertura e exclusões contadas.

    `cobertura` é a recalculada sobre a produção territorial (a que é avaliada);
    `cobertura_da_ingestao` fica registrada como origem.
    """

    producao: DatasetRef
    auxiliares: tuple[DatasetRef, ...]
    cobertura: DatasetRef | None
    exclusoes: dict[str, int]
    cobertura_da_ingestao: DatasetRef | None = None


def ler_datasets(pasta: Path) -> list[DatasetRef]:
    """Um `DatasetRef` por linha de `pasta/datasets.jsonl`.

    Raises:
        ConfigInvalida: arquivo ausente, ilegível ou com linha inválida.
    """
    caminho = pasta / "datasets.jsonl"
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
        return [DatasetRef.model_validate_json(linha) for linha in linhas if linha.strip()]
    except (OSError, ValueError, ValidationError) as erro:
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


def integridade_do_registro(
    registro: RegistroTemporal, *, corte: datetime | None = None
) -> dict[str, EstadoIntegridade]:
    """Integridade por versão: a da versão, piorada pelas observações dela.

    Quarentena observada prevalece; tentativa com bytes que não terminou em `OBTIDO` (falha de
    coleta) deixa a versão `NAO_VERIFICADO`, nunca `OK`. Com `corte`, só contam as observações
    até ele e só entram versões observadas até ele (as posteriores não alteram uma execução
    histórica nem o seu `run_id`).
    """
    observacoes = [o for o in registro.observacoes if corte is None or o.observado_em <= corte]
    vistas = {o.artifact_id for o in observacoes}
    estados = {
        a: v.integridade for a, v in registro.versoes.items() if corte is None or a in vistas
    }
    for obs in observacoes:
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


def _exigir_escopo_do_piloto(
    artefatos: list[str], registro: RegistroTemporal, config: RunConfig
) -> None:
    """Cada versão da produção é do SIA-PA, da UF e de uma competência do piloto."""
    piloto = config.piloto
    if piloto is None:
        raise ConfigInvalida("validate_ingest_sem_piloto")
    competencias = {str(c) for c in piloto.competencias_processamento}
    for artefato in artefatos:
        chave = registro.versoes[artefato].chave
        if chave.fonte is not FamiliaFonte.SIA_PA:
            raise ConfigInvalida(
                f"producao_com_fonte_invalida artefato={artefato} fonte={chave.fonte}"
            )
        if chave.uf != piloto.uf or str(chave.competencia_arquivo) not in competencias:
            raise ConfigInvalida(
                f"producao_fora_do_piloto artefato={artefato} uf={chave.uf} "
                f"competencia={chave.competencia_arquivo}"
            )


def _exigir_producao_coerente(
    producao: list[DatasetRef], registro: RegistroTemporal, config: RunConfig
) -> dict[str, SelecaoVersao]:
    """Produção do SIA-PA, do piloto e das versões selecionadas; devolve as seleções INCOMPLETA."""
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
    _exigir_escopo_do_piloto(artefatos, registro, config)
    incompletas = exigir_versao_selecionavel(artefatos, registro, config)
    corte = config.corte_observacao
    if corte is None:
        return incompletas
    for artefato in artefatos:
        if not any(
            o.artifact_id == artefato
            and o.resultado is ResultadoTentativa.OBTIDO
            and o.observado_em <= corte
            for o in registro.observacoes
        ):
            raise ConfigInvalida(f"producao_observada_apos_o_corte artefato={artefato}")
    return incompletas


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


def _exigir_linhagem(con: duckdb.DuckDBPyConnection, ref: DatasetRef) -> None:
    """Cada linha pertence a um artefato declarado pelo próprio conjunto (nunca a outro)."""
    divergentes = con.execute(
        "SELECT count(*) FROM read_parquet($c) "
        "WHERE artifact_id IS NULL OR NOT list_contains($a, artifact_id)",
        {"c": ref.caminho, "a": list(ref.artifact_ids)},
    ).fetchall()[0][0]
    if divergentes:
        raise ConteudoDivergente(
            f"linhagem_divergente schema={ref.schema_id} dataset={ref.dataset_id} "
            f"linhas={divergentes}"
        )


def _conferir(con: duckdb.DuckDBPyConnection, refs: list[DatasetRef]) -> set[str]:
    """Conteúdo, tipo, colunas obrigatórias e linhagem de cada conjunto; devolve as presentes."""
    fisicas: set[str] = set()
    for ref in refs:
        verificar_conteudo(con, ref)
        presentes = conferir_tipos_fisicos(con, ref)
        exigir_colunas_obrigatorias(con, ref, presentes)
        if "artifact_id" in presentes:
            _exigir_linhagem(con, ref)
        fisicas |= presentes
    return fisicas


def _unir(con: duckdb.DuckDBPyConnection, refs: list[DatasetRef], fisicas: set[str]) -> list[str]:
    """Tabela `_UNIAO` com todas as linhas físicas dos conjuntos já conferidos (sem deduplicar)."""
    schema_id = refs[0].schema_id
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


def exigir_sem_deletados(con: duckdb.DuckDBPyConnection, producao: DatasetRef) -> None:
    """Caminho direto (`--entrada`): sem registro de exclusões, recusa produção com deletados.

    Erro de leitura não é tratado aqui: segue para o motor, que o registra como falha operacional.

    Raises:
        ConfigInvalida: alguma linha com `deletado` verdadeiro.
    """
    try:
        descricao = con.execute(
            "DESCRIBE SELECT * FROM read_parquet($c)", {"c": producao.caminho}
        ).fetchall()
        if "deletado" not in {str(c[0]) for c in descricao}:
            return
        linhas = con.execute(
            "SELECT count(*) FROM read_parquet($c) WHERE deletado IS TRUE",
            {"c": producao.caminho},
        ).fetchall()[0][0]
    except duckdb.Error:
        logger.info("pre_checagem_de_deletados_sem_leitura caminho=%s", producao.caminho)
        return
    if linhas:
        raise ConfigInvalida(f"producao_com_registros_deletados linhas={linhas}")


def _recortar_populacao(
    con: duckdb.DuckDBPyConnection,
    colunas: list[str],
    municipios: frozenset[str],
    competencias: list[str],
) -> dict[str, int]:
    """Mantém só a população do piloto; conta as excluídas por motivo (nunca somem em silêncio).

    Um motivo por linha, na precedência do T10 (`evaluation/split.py`).

    Raises:
        ConfigInvalida: produção sem coluna exigida ou população vazia após o recorte.
    """
    for coluna in ("municipio_estabelecimento", "competencia_processamento"):
        if coluna not in colunas:
            raise ConfigInvalida(f"territorio_sem_coluna coluna={coluna}")
    valores = {"m": sorted(municipios), "c": sorted(competencias)}
    exclusoes: dict[str, int] = {}
    for motivo, condicao in _EXCLUSOES:
        parametros = {k: v for k, v in valores.items() if f"${k}" in condicao}
        consulta = f"SELECT count(*) FROM {_UNIAO} WHERE {condicao}"  # noqa: S608
        quantidade = int(con.execute(consulta, parametros).fetchall()[0][0])
        con.execute(f"DELETE FROM {_UNIAO} WHERE {condicao}", parametros)  # noqa: S608
        if quantidade:
            exclusoes[motivo] = quantidade
    restantes = con.execute(f"SELECT count(*) FROM {_UNIAO}").fetchall()[0][0]  # noqa: S608
    if not restantes:
        raise ConfigInvalida(f"populacao_vazia_apos_recorte exclusoes={exclusoes}")
    return exclusoes


def _exigir_row_id_unico(con: duckdb.DuckDBPyConnection) -> None:
    repetidos = con.execute(
        f"SELECT count(*) FROM (SELECT row_id FROM {_UNIAO} "  # noqa: S608
        "GROUP BY row_id HAVING count(*) > 1)"
    ).fetchall()[0][0]
    if repetidos:
        raise FalhaOperacionalErro(f"producao_com_row_id_repetido chaves={repetidos}")


def incompletude_da_cobertura(
    con: duckdb.DuckDBPyConnection, cobertura: DatasetRef
) -> dict[str, str]:
    """Competência → motivo das marcas `sia_pa_incompleto` da cobertura da ingestão.

    Lê o formato de `ingest.coverage._marcar_incompleto`
    (`sia_pa_incompleto competencia=AAAAMM motivo=…`, seguido de `; ` e o motivo original).
    """
    linhas = con.execute(
        "SELECT DISTINCT motivo FROM read_parquet($c) "
        "WHERE starts_with(motivo, 'sia_pa_incompleto ') ORDER BY motivo",
        {"c": cobertura.caminho},
    ).fetchall()
    incompleto: dict[str, str] = {}
    for (motivo,) in linhas:
        marca = _MARCA_INCOMPLETO.match(str(motivo))
        if marca is None:
            raise ValueError(f"marca_de_incompletude_ilegivel motivo={motivo}")
        incompleto[marca.group(1)] = marca.group(2)
    return incompleto


def _competencias_do_piloto(config: RunConfig) -> list[str]:
    piloto = config.piloto
    return [str(c) for c in piloto.competencias_processamento] if piloto else []


def _recalcular_cobertura(
    incompleto: dict[str, str],
    derivados: tuple[DatasetRef, list[DatasetRef]],
    config: RunConfig,
    destino: Path,
) -> DatasetRef:
    """Cobertura sobre a produção territorial, com as marcas de incompletude da ingestão.

    Os auxiliares são os conjuntos originais da ingestão (com `reconciliacao`, já conferidos):
    não passam por recorte, e a perda de linhas declarada neles continua tornando a célula
    insuficiente.
    """
    producao, auxiliares = derivados
    return build_coverage(
        [producao],
        auxiliares,
        _competencias_do_piloto(config),
        destino / "cobertura",
        runtime=config.runtime,
        origem_dados=producao.origem_dados,
        sia_pa_incompleto=incompleto,
    )


def preparar_insumos_ingest(
    con: duckdb.DuckDBPyConnection,
    datasets: list[DatasetRef],
    regras: list[RuleSpec],
    contexto: tuple[RunConfig, RegistroTemporal, frozenset[str]],
    destino: Path,
) -> InsumosIngest:
    """Confere todos os conjuntos do ingest e só então grava as relações derivadas em `destino`.

    Raises:
        ConfigInvalida: origens diferentes, sem produção, várias coberturas, versões concorrentes,
            parte selecionada ausente da pasta, artefato fora do registro ou observado só depois
            do corte.
        FalhaOperacionalErro: `row_id` repetido na união da produção.
        ValueError: conteúdo ou tipo físico divergente do `DatasetRef`; coluna não anulável do
            esquema ausente ou nula em qualquer conjunto (`ConteudoDivergente`, antes de gravar).
    """
    config, registro, municipios = contexto
    producao, auxiliares, cobertura = _classificar(datasets, regras)
    incompletas = _exigir_producao_coerente(producao, registro, config)
    grupos = [producao, *(refs for refs in auxiliares.values() if refs)]
    fisicas = [_conferir(con, refs) for refs in grupos]
    if cobertura is not None:
        _conferir(con, [cobertura])
    incompleto = incompletude_da_cobertura(con, cobertura) if cobertura is not None else {}
    colunas = _unir(con, producao, fisicas[0])
    _exigir_row_id_unico(con)
    exclusoes = _recortar_populacao(con, colunas, municipios, _competencias_do_piloto(config))
    incompleto = marcas_de_incompletude(con, _UNIAO, incompletas) | incompleto
    ref_producao = _gravar(con, colunas, producao, destino)
    derivados = [
        _gravar(con, _unir(con, refs, presentes), refs, destino)
        for refs, presentes in zip(grupos[1:], fisicas[1:], strict=True)
    ]
    recalculada = None
    if cobertura is not None:
        originais = [ref for refs in grupos[1:] for ref in refs]
        recalculada = _recalcular_cobertura(incompleto, (ref_producao, originais), config, destino)
    logger.info(
        "insumos_ingest_prontos producao=%s exclusoes=%s", ref_producao.dataset_id, exclusoes
    )
    return InsumosIngest(ref_producao, tuple(derivados), recalculada, exclusoes, cobertura)
