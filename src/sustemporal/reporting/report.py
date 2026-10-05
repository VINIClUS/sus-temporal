"""Relatório do piloto de observabilidade (T05): o que as fontes públicas permitem observar.

Entradas: os `DatasetRef` do `ingest` (SIA-PA, auxiliares e `cobertura.v1`) e, quando houver, a
`selecao_versoes.v1` de cada conjunto SIA-PA. Sem `cobertura.v1` a entrada é recusada
(`relatorio_sem_cobertura`), assim como a coorte sem nenhuma competência na cobertura
(`coorte_sem_competencias_na_cobertura`): disponibilidade vazia seria lida como resultado, não
como evidência ausente. O recorte territorial é explícito: linhas do SIA-PA cujo município do
estabelecimento não está em `municipios_ibge6` do território da coorte são excluídas com motivo
`fora_do_territorio`. A disponibilidade das tabelas vem da cobertura recalculada só com as linhas
incluídas (`report_cobertura.py`). A pertença é a lista atual do território, sem versão por
competência: `pertenca=HISTORICA` é recusada (`pertenca_historica_nao_implementada`) até haver
pertença versionada. Competência com versões de conteúdo concorrentes do SIA-PA sai da população
(`versoes_concorrentes`, `report_republicacao.py`): o relatório não escolhe versão. Toda razão sai
com numerador e denominador; o relatório é sempre exploratório (pré-G0) e nunca libera portão.
"""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import EvaluationReport, OrigemDados, RuntimeConfig
from sustemporal.contracts.base import hash_canonico
from sustemporal.contracts.evaluation import ValorMetrica
from sustemporal.contracts.experiment import ModoExecucao, PertencaGeografica
from sustemporal.duck import conectar
from sustemporal.errors import ConfigInvalida
from sustemporal.ingest.territorio import carregar_territorio, municipios_ibge6
from sustemporal.reporting.report_cobertura import recalcular_cobertura
from sustemporal.reporting.report_publicacao import publicar_tabelas
from sustemporal.reporting.report_republicacao import (
    artefatos_excluidos,
    marcas_de_concorrencia,
    notas_de_concorrencia,
    versoes_concorrentes,
)
from sustemporal.reporting.report_selecao import carregar_disponibilidade, carregar_inconclusivos
from sustemporal.reporting.report_tabelas import (
    carregar_registros_piloto,
    carregar_rotulos,
    criar_tabelas_registros,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    import duckdb

    from sustemporal.contracts import ChaveArtefato, CohortSpec, DatasetRef, ResultadoTentativa
    from sustemporal.reporting.report_republicacao import VersoesConcorrentes

__all__ = ["build_pilot_report", "exigir_pertenca_implementada"]

logger = logging.getLogger(__name__)

ESCALA_RAZAO = Decimal("0.000001")
AVISO_SINTETICO = (
    "dados_sinteticos_exploratorio origem=SINTETICO: tabelas geradas por fixtures; nenhuma "
    "contagem descreve o SUS"
)
AVISO_PRE_G0 = (
    "pre_g0_exploratorio: relatório de observabilidade; não é decisão G0 nem libera portão"
)


def _agora() -> datetime:
    return datetime.now(UTC)


def exigir_pertenca_implementada(cohort: CohortSpec) -> None:
    """Recusa `pertenca=HISTORICA`: há uma lista de municípios por território, sem versão.

    Raises:
        ConfigInvalida: coorte com pertença histórica.
    """
    if cohort.pertenca is PertencaGeografica.HISTORICA:
        raise ConfigInvalida(
            f"pertenca_historica_nao_implementada coorte={cohort.cohort_id} "
            f"territorio={cohort.territorio}"
        )


def _origem(datasets: Sequence[DatasetRef]) -> OrigemDados:
    origens = {dataset.origem_dados for dataset in datasets}
    if len(origens) > 1:
        raise ValueError(f"relatorio_com_origens_misturadas origens={sorted(origens)}")
    return origens.pop() if origens else OrigemDados.SINTETICO


def _cobertura_da_ingestao(datasets: Sequence[DatasetRef]) -> DatasetRef:
    ingest = next((d for d in datasets if d.schema_id == "cobertura.v1"), None)
    if ingest is None:
        raise ConfigInvalida(
            f"relatorio_sem_cobertura esquema=cobertura.v1 datasets={len(datasets)}"
        )
    return ingest


def _entradas_validas(
    datasets: Sequence[DatasetRef], cohort: CohortSpec
) -> tuple[OrigemDados, DatasetRef]:
    """Origem única e `cobertura.v1` da ingestão; recusa coorte e entradas antes de qualquer I/O."""
    exigir_pertenca_implementada(cohort)
    return _origem(datasets), _cobertura_da_ingestao(datasets)


def _razao(nome: str, numerador: int, denominador: int, estrato: str = "TOTAL") -> ValorMetrica:
    valor = (
        (Decimal(numerador) / Decimal(denominador)).quantize(ESCALA_RAZAO) if denominador else None
    )
    return ValorMetrica(
        nome=nome, estrato=estrato, numerador=numerador, denominador=denominador, valor=valor
    )


def _metricas(con: duckdb.DuckDBPyConnection, fisicas: int) -> list[ValorMetrica]:
    incluidas = con.execute("SELECT count(*) FROM base WHERE exclusao IS NULL").fetchall()[0][0]
    metricas = [_razao("fracao_registros_incluidos", int(incluidas), fisicas)]
    for campo, ausentes, denominador in con.execute(
        "SELECT campo, ausentes, denominador FROM campos"
    ).fetchall():
        metricas.append(_razao("taxa_ausencia_campo", int(ausentes), int(denominador), campo))
    estratos = con.execute(
        "SELECT rule_id || '|' || fonte || '|' || base, "
        "sum(linhas) FILTER (WHERE classe <> 'selecionada'), sum(linhas) "
        "FROM inconclusivos GROUP BY ALL ORDER BY 1"
    ).fetchall()
    for estrato, inconclusivas, total in estratos:
        metricas.append(
            _razao("taxa_inconclusivo", int(inconclusivas or 0), int(total), str(estrato))
        )
    return metricas


@dataclass(frozen=True)
class _Insumos:
    """Entradas validadas do relatório e o que as tabelas e as notas precisam saber delas."""

    datasets: list[DatasetRef]
    cohort: CohortSpec
    out: Path
    origem: OrigemDados
    ingestao: DatasetRef
    municipios: frozenset[str]
    concorrentes: list[VersoesConcorrentes]
    observacoes: Mapping[str, ResultadoTentativa]
    runtime: RuntimeConfig


def _insumos(
    datasets: list[DatasetRef],
    cohort: CohortSpec,
    out: Path,
    *,
    observacoes: Mapping[str, ResultadoTentativa] | None,
    runtime: RuntimeConfig | None,
    chaves: Mapping[str, ChaveArtefato] | None,
) -> _Insumos:
    """Valida a coorte e as entradas antes de qualquer I/O de relatório e reúne o que usam."""
    origem, ingestao = _entradas_validas(datasets, cohort)
    municipios = municipios_ibge6(carregar_territorio(Path(cohort.territorio), uf=cohort.uf))
    concorrentes = versoes_concorrentes(datasets, chaves or {})
    return _Insumos(
        datasets,
        cohort,
        out,
        origem,
        ingestao,
        municipios,
        concorrentes,
        observacoes or {},
        runtime or RuntimeConfig(),
    )


def _notas(insumos: _Insumos) -> list[str]:
    cohort = insumos.cohort
    notas = [AVISO_PRE_G0]
    if insumos.origem is OrigemDados.SINTETICO:
        notas.insert(0, AVISO_SINTETICO)
    notas.append(
        f"recorte_territorial territorio={cohort.territorio} municipios={len(insumos.municipios)} "
        f"criterio={cohort.criterio_geografico.value} pertenca={cohort.pertenca.value}"
    )
    notas.extend(notas_de_concorrencia(insumos.concorrentes))
    if not any(d.schema_id == "selecao_versoes.v1" for d in insumos.datasets):
        notas.append("selecao_ausente: sem selecao_versoes.v1, inconclusivos não classificados")
    return notas


def _report_id(insumos: _Insumos) -> str:
    conteudo: dict[str, object] = {
        "datasets": sorted(d.dataset_id for d in insumos.datasets),
        "coorte": insumos.cohort.model_dump(mode="json"),
    }
    excluidos = artefatos_excluidos(insumos.concorrentes)
    if excluidos:
        conteudo["versoes_concorrentes"] = excluidos
    return f"piloto_{hash_canonico(conteudo)[:24]}"


def _tabelas(
    con: duckdb.DuckDBPyConnection, insumos: _Insumos
) -> tuple[list[DatasetRef], DatasetRef, list[ValorMetrica], int]:
    """Carrega a população, recalcula a cobertura e publica as tabelas (e as linhas físicas)."""
    i = insumos
    sia_pa = [d for d in i.datasets if d.schema_id == "sia_pa.v1"]
    selecoes = [d for d in i.datasets if d.schema_id == "selecao_versoes.v1"]
    fisicas = carregar_registros_piloto(con, sia_pa)
    excluidos = artefatos_excluidos(i.concorrentes)
    criar_tabelas_registros(con, i.cohort, i.municipios, concorrentes=excluidos)
    cobertura = recalcular_cobertura(
        con,
        i.datasets,
        i.cohort,
        i.out,
        ingest=i.ingestao,
        runtime=i.runtime,
        origem=i.origem,
        incompletas=marcas_de_concorrencia(con, i.concorrentes),
    )
    carregar_rotulos(con, sia_pa, i.out, runtime=i.runtime)
    carregar_inconclusivos(con, selecoes, i.observacoes)
    carregar_disponibilidade(con, cobertura, i.cohort)
    tabelas = publicar_tabelas(con, i.out, i.datasets, i.origem)
    return tabelas, cobertura, _metricas(con, fisicas), fisicas


def build_pilot_report(
    datasets: list[DatasetRef],
    cohort: CohortSpec,
    out: Path,
    *,
    observacoes: Mapping[str, ResultadoTentativa] | None = None,
    runtime: RuntimeConfig | None = None,
    relogio: Callable[[], datetime] = _agora,
    chaves: Mapping[str, ChaveArtefato] | None = None,
) -> EvaluationReport:
    """Produz contagens, ausências, defasagens, rótulos, inconclusivos e disponibilidade.

    `chaves` (id do artefato → chave com UF, competência do arquivo e parte) permite achar versões
    de conteúdo concorrentes do SIA-PA, que saem da população (`report_republicacao.py`); sem ela
    nada é detectado. `observacoes` (id → resultado) classifica a ausência das seleções: observação
    citada fora dele dá `ausente_tentativa_sem_resultado_conhecido`, nunca `ausente_sem_tentativa`.

    Raises:
        ValueError: conjuntos de origens diferentes ou divergentes do `DatasetRef`.
        ConfigInvalida: coorte com pertença histórica ou território inválido, entrada sem
            `cobertura.v1` ou coorte sem nenhuma competência na cobertura (nada é gravado em `out`).
    """
    insumos = _insumos(
        datasets, cohort, out, observacoes=observacoes, runtime=runtime, chaves=chaves
    )
    with closing(conectar(insumos.runtime)) as con:
        tabelas, cobertura, metricas, fisicas = _tabelas(con, insumos)
    relatorio = EvaluationReport(
        report_id=_report_id(insumos),
        modo=ModoExecucao.EXPLORATORIO,
        origem_dados=insumos.origem,
        metricas=tuple(metricas),
        tabelas=(*tabelas, cobertura),
        notas=tuple(_notas(insumos)),
        criado_em=relogio(),
    )
    logger.info(
        "relatorio_piloto report=%s fisicas=%s tabelas=%s",
        relatorio.report_id,
        fisicas,
        len(tabelas),
    )
    return relatorio
