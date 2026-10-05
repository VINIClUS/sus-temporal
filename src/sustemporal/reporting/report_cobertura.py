"""Cobertura do relatório recalculada sobre a população do território (T05).

A cobertura da ingestão é estadual: um registro de outro município com atendimento nulo deixaria
a célula INSUFICIENTE para todo o DRS XI. O relatório publica um `sia_pa.v1` só com as linhas
incluídas (a mesma população dos denominadores) e chama `build_coverage` sobre ele, com os mesmos
auxiliares e as competências da cobertura da ingestão no intervalo da coorte. As marcas
`sia_pa_incompleto` da ingestão continuam valendo, e o relatório acrescenta as suas (versões
concorrentes, `report_republicacao.py`). Competência com linha de produção nos conjuntos
`sia_pa.v1` ingeridos e nenhuma linha incluída fica `populacao_vazia_no_recorte` (limitação
amostral), nunca `sia_pa_ausente`. A presença sai desses conjuntos, nunca do texto do motivo da
cobertura: competência sem conjunto legível continua ausente, com o motivo original. Coorte sem
nenhuma competência na cobertura da ingestão é recusada (`coorte_sem_competencias_na_cobertura`):
disponibilidade vazia seria lida como resultado, não como ingestão que não cobre a coorte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts import DatasetRef
from sustemporal.contracts.records import calcular_dataset_id
from sustemporal.errors import ConfigInvalida
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.coverage import build_coverage, marcas_sia_pa_incompleto
from sustemporal.ingest.sia_pa import carregar_conferido, gravar_parquet, produtor
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import CohortSpec, OrigemDados, RuntimeConfig

__all__ = ["recalcular_cobertura"]

_FORA_DOS_AUXILIARES = frozenset({"sia_pa.v1", "cobertura.v1", "selecao_versoes.v1"})


def _publicar_recorte(
    con: duckdb.DuckDBPyConnection, sia_pa: Sequence[DatasetRef], out: Path, origem: OrigemDados
) -> DatasetRef:
    colunas = [coluna.nome for coluna in carregar_esquema("sia_pa.v1").colunas]
    con.execute(
        "CREATE TABLE pa_recortada AS SELECT * FROM pa "
        "WHERE row_id IN (SELECT row_id FROM base WHERE exclusao IS NULL)"
    )
    hash_logico = hash_logico_relacao(con, "pa_recortada", colunas)
    artefatos = tuple(sorted({a for d in sia_pa for a in d.artifact_ids}))
    dataset_id = calcular_dataset_id("sia_pa.v1", hash_logico, artefatos)
    out.mkdir(parents=True, exist_ok=True)
    destino = out / f"{dataset_id}.parquet"
    gravar_parquet(con, "pa_recortada", destino)
    contagem = con.execute("SELECT count(*) FROM pa_recortada").fetchall()[0][0]
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id="sia_pa.v1",
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=int(contagem),
        artifact_ids=artefatos,
        origem_dados=origem,
        produzido_por=produtor("reporting.report_cobertura.recorte_territorial"),
    )


def _marcas_e_competencias(
    con: duckdb.DuckDBPyConnection, cobertura: DatasetRef, cohort: CohortSpec
) -> tuple[dict[str, str], list[str]]:
    """Marcas de incompletude e competências da cobertura da ingestão dentro da coorte.

    Raises:
        ConfigInvalida: nenhuma competência da cobertura no intervalo da coorte.
    """
    carregar_conferido(con, cobertura, carregar_esquema("cobertura.v1"), "cobertura_ingest")
    motivos = con.execute("SELECT DISTINCT motivo FROM cobertura_ingest").fetchall()
    na_cobertura = con.execute(
        "SELECT DISTINCT competencia, competencia BETWEEN $inicio AND $fim AS dentro "
        "FROM cobertura_ingest WHERE competencia IS NOT NULL ORDER BY competencia",
        {"inicio": cohort.inicio.valor, "fim": cohort.fim.valor},
    ).fetchall()
    competencias = [str(c) for c, dentro in na_cobertura if dentro]
    if not competencias:
        raise ConfigInvalida(
            f"coorte_sem_competencias_na_cobertura coorte={cohort.cohort_id} "
            f"inicio={cohort.inicio.valor} fim={cohort.fim.valor} "
            f"cobertura={','.join(str(c) for c, _ in na_cobertura) or '-'}"
        )
    marcas = marcas_sia_pa_incompleto(str(m) for (m,) in motivos if m is not None)
    return marcas, competencias


def _competencias_com_producao(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Competências de processamento com linha não deletada nos `sia_pa.v1` ingeridos."""
    linhas = con.execute(
        "SELECT DISTINCT competencia_processamento FROM pa "
        "WHERE NOT deletado AND competencia_processamento IS NOT NULL ORDER BY 1"
    ).fetchall()
    return [str(c) for (c,) in linhas]


def recalcular_cobertura(
    con: duckdb.DuckDBPyConnection,
    datasets: Sequence[DatasetRef],
    cohort: CohortSpec,
    out: Path,
    *,
    ingest: DatasetRef,
    runtime: RuntimeConfig,
    origem: OrigemDados,
    incompletas: Mapping[str, str] | None = None,
) -> DatasetRef:
    """`cobertura.v1` da população incluída, recalculada a partir da cobertura `ingest`.

    `incompletas` (competência → motivo) acrescenta marcas `sia_pa_incompleto` às da ingestão, que
    prevalecem na mesma competência.

    Raises:
        ConfigInvalida: nenhuma competência da cobertura `ingest` no intervalo da coorte;
            recusa antes de gravar qualquer arquivo em `out`.
    """
    marcas, competencias = _marcas_e_competencias(con, ingest, cohort)
    sia_pa = [d for d in datasets if d.schema_id == "sia_pa.v1"]
    recortes = [_publicar_recorte(con, sia_pa, out / "recorte", origem)] if sia_pa else []
    auxiliares = [d for d in datasets if d.schema_id not in _FORA_DOS_AUXILIARES]
    destino = out / "cobertura"
    destino.mkdir(parents=True, exist_ok=True)
    return build_coverage(
        recortes,
        auxiliares,
        competencias,
        destino,
        runtime=runtime,
        origem_dados=origem,
        sia_pa_incompleto={**(incompletas or {}), **marcas},
        sia_pa_presente_em=_competencias_com_producao(con),
    )
