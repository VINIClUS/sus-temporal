"""Relatório do piloto de observabilidade (T05): o que as fontes públicas permitem observar.

Entradas: os `DatasetRef` do `ingest` (SIA-PA, auxiliares e `cobertura.v1`) e, quando houver, a
`selecao_versoes.v1` de cada conjunto SIA-PA. Sem `cobertura.v1` a entrada é recusada
(`relatorio_sem_cobertura`), assim como a coorte sem nenhuma competência na cobertura
(`coorte_sem_competencias_na_cobertura`): disponibilidade vazia seria lida como resultado, não
como evidência ausente. O recorte territorial é explícito: linhas do SIA-PA cujo município do
estabelecimento não está em `municipios_ibge6` do território da coorte são excluídas com motivo
`fora_do_territorio`. A disponibilidade das tabelas vem da cobertura recalculada só com as linhas
incluídas (`report_cobertura.py`). Toda razão sai com numerador e denominador; o relatório é
sempre exploratório (pré-G0) e nunca libera portão.
"""

from __future__ import annotations

import logging
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import EvaluationReport, OrigemDados, RuntimeConfig
from sustemporal.contracts.base import hash_canonico
from sustemporal.contracts.evaluation import ValorMetrica
from sustemporal.contracts.experiment import ModoExecucao
from sustemporal.duck import conectar
from sustemporal.errors import ConfigInvalida
from sustemporal.ingest.territorio import carregar_territorio, municipios_ibge6
from sustemporal.reporting.report_cobertura import recalcular_cobertura
from sustemporal.reporting.report_publicacao import publicar_tabelas
from sustemporal.reporting.report_selecao import carregar_disponibilidade, carregar_inconclusivos
from sustemporal.reporting.report_tabelas import (
    carregar_registros_piloto,
    carregar_rotulos,
    criar_tabelas_registros,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    import duckdb

    from sustemporal.contracts import CohortSpec, DatasetRef, ResultadoTentativa

__all__ = ["build_pilot_report"]

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


def _notas(
    origem: OrigemDados, cohort: CohortSpec, municipios: frozenset[str], *, selecoes: int
) -> list[str]:
    notas = [AVISO_PRE_G0]
    if origem is OrigemDados.SINTETICO:
        notas.insert(0, AVISO_SINTETICO)
    notas.append(
        f"recorte_territorial territorio={cohort.territorio} municipios={len(municipios)} "
        f"criterio={cohort.criterio_geografico.value} pertenca={cohort.pertenca.value}"
    )
    if not selecoes:
        notas.append("selecao_ausente: sem selecao_versoes.v1, inconclusivos não classificados")
    return notas


def _report_id(datasets: Sequence[DatasetRef], cohort: CohortSpec) -> str:
    conteudo = {
        "datasets": sorted(d.dataset_id for d in datasets),
        "coorte": cohort.model_dump(mode="json"),
    }
    return f"piloto_{hash_canonico(conteudo)[:24]}"


def build_pilot_report(
    datasets: list[DatasetRef],
    cohort: CohortSpec,
    out: Path,
    *,
    observacoes: Mapping[str, ResultadoTentativa] | None = None,
    runtime: RuntimeConfig | None = None,
    relogio: Callable[[], datetime] = _agora,
) -> EvaluationReport:
    """Produz contagens, ausências, defasagens, rótulos, inconclusivos e disponibilidade.

    Raises:
        ValueError: conjuntos de origens diferentes ou divergentes do `DatasetRef`.
        ConfigInvalida: território da coorte inválido, entrada sem `cobertura.v1` ou coorte sem
            nenhuma competência na cobertura (nada é gravado em `out`).
    """
    origem = _origem(datasets)
    ingestao = _cobertura_da_ingestao(datasets)
    municipios = municipios_ibge6(carregar_territorio(Path(cohort.territorio), uf=cohort.uf))
    sia_pa = [d for d in datasets if d.schema_id == "sia_pa.v1"]
    selecoes = [d for d in datasets if d.schema_id == "selecao_versoes.v1"]
    execucao = runtime or RuntimeConfig()
    with closing(conectar(execucao)) as con:
        fisicas = carregar_registros_piloto(con, sia_pa)
        criar_tabelas_registros(con, cohort, municipios)
        cobertura = recalcular_cobertura(
            con, datasets, cohort, out, ingest=ingestao, runtime=execucao, origem=origem
        )
        carregar_rotulos(con, sia_pa, out, runtime=execucao)
        carregar_inconclusivos(con, selecoes, observacoes or {})
        carregar_disponibilidade(con, cobertura, cohort)
        tabelas = publicar_tabelas(con, out, datasets, origem)
        metricas = _metricas(con, fisicas)
    relatorio = EvaluationReport(
        report_id=_report_id(datasets, cohort),
        modo=ModoExecucao.EXPLORATORIO,
        origem_dados=origem,
        metricas=tuple(metricas),
        tabelas=(*tabelas, cobertura),
        notas=tuple(_notas(origem, cohort, municipios, selecoes=len(selecoes))),
        criado_em=relogio(),
    )
    logger.info(
        "relatorio_piloto report=%s fisicas=%s tabelas=%s",
        relatorio.report_id,
        fisicas,
        len(tabelas),
    )
    return relatorio
