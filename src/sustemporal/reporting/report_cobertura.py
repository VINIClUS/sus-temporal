"""Cobertura do relatório recalculada sobre a população do território (T05).

A cobertura da ingestão é estadual: um registro de outro município com atendimento nulo deixaria
a célula INSUFICIENTE para todo o DRS XI. O relatório publica um `sia_pa.v1` só com as linhas
incluídas (a mesma população dos denominadores) e chama `build_coverage` sobre ele, com os mesmos
auxiliares e as competências da cobertura da ingestão no intervalo da coorte. As marcas
`sia_pa_incompleto` da ingestão continuam valendo. Competência com SIA-PA na ingestão e nenhuma
linha incluída fica `populacao_vazia_no_recorte` (limitação amostral), nunca `sia_pa_ausente`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts import DatasetRef
from sustemporal.contracts.records import calcular_dataset_id
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.coverage import build_coverage, marcas_sia_pa_incompleto
from sustemporal.ingest.sia_pa import carregar_conferido, gravar_parquet, produtor
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Sequence
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
) -> tuple[dict[str, str], list[str], list[str]]:
    carregar_conferido(con, cobertura, carregar_esquema("cobertura.v1"), "cobertura_ingest")
    motivos = con.execute("SELECT DISTINCT motivo FROM cobertura_ingest").fetchall()
    competencias = con.execute(
        "SELECT DISTINCT competencia FROM cobertura_ingest "
        "WHERE competencia BETWEEN $inicio AND $fim ORDER BY competencia",
        {"inicio": cohort.inicio.valor, "fim": cohort.fim.valor},
    ).fetchall()
    presentes = con.execute(
        "SELECT DISTINCT competencia FROM cobertura_ingest "
        "WHERE coalesce(motivo, '') NOT LIKE 'sia_pa_ausente%' ORDER BY competencia"
    ).fetchall()
    marcas = marcas_sia_pa_incompleto(str(m) for (m,) in motivos if m is not None)
    return marcas, [str(c) for (c,) in competencias], [str(c) for (c,) in presentes]


def recalcular_cobertura(
    con: duckdb.DuckDBPyConnection,
    datasets: Sequence[DatasetRef],
    cohort: CohortSpec,
    out: Path,
    *,
    runtime: RuntimeConfig,
    origem: OrigemDados,
) -> DatasetRef | None:
    """`cobertura.v1` da população incluída; None sem cobertura da ingestão."""
    ingest = next((d for d in datasets if d.schema_id == "cobertura.v1"), None)
    if ingest is None:
        return None
    marcas, competencias, presentes = _marcas_e_competencias(con, ingest, cohort)
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
        sia_pa_incompleto=marcas,
        sia_pa_presente_em=presentes,
    )
