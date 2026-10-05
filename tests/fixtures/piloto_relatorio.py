"""Apoio aos testes do relatório do piloto (T05, SINTETICO): coorte e leitura das tabelas."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from sustemporal.contracts import CohortSpec, EvaluationReport

if TYPE_CHECKING:
    from sustemporal.contracts.evaluation import ValorMetrica

__all__ = ["coorte_piloto", "linhas_tabela", "metrica", "relatorio_gravado"]

DRS_XI = Path(__file__).resolve().parents[2] / "catalog" / "territorio" / "drs_xi.yaml"


def coorte_piloto(
    inicio: str = "201801", fim: str = "201812", instrumentos: tuple[str, ...] = ()
) -> CohortSpec:
    return CohortSpec.model_validate(
        {
            "cohort_id": "piloto_sintetico",
            "uf": "SP",
            "territorio": str(DRS_XI),
            "inicio": inicio,
            "fim": fim,
            "instrumentos": instrumentos,
        }
    )


def linhas_tabela(relatorio: EvaluationReport, schema_id: str) -> list[dict[str, Any]]:
    """Linhas da tabela do relatório com o esquema pedido (exatamente uma)."""
    (tabela,) = [t for t in relatorio.tabelas if t.schema_id == schema_id]
    with closing(duckdb.connect()) as con:
        cursor = con.execute("SELECT * FROM read_parquet($c)", {"c": tabela.caminho})
        nomes = [d[0] for d in cursor.description]
        return [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]


def metrica(relatorio: EvaluationReport, nome: str, estrato: str = "TOTAL") -> ValorMetrica:
    (valor,) = [m for m in relatorio.metricas if m.nome == nome and m.estrato == estrato]
    return valor


def relatorio_gravado(pasta: Path) -> EvaluationReport:
    """O `relatorio.json` da única execução de `pilot-report` sob `<pasta>/saidas/pilot`."""
    (execucao,) = sorted(p for p in (pasta / "saidas" / "pilot").iterdir() if p.is_dir())
    texto = (execucao / "relatorio.json").read_text(encoding="utf-8")
    return EvaluationReport.model_validate(json.loads(texto))
