"""Execução do motor sobre cenários SINTETICOS e leitura das saídas para os testes."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq

from sustemporal.contracts.config import RunConfig
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from tests.fixtures.regras_cenario import materializar, snapshot_vazio

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import SnapshotSet
    from tests.fixtures.regras_cenario import CenarioRegras

__all__ = ["avaliacoes_por_chave", "executar", "regras_so_de_c", "saida", "tabela"]


def regras_so_de_c() -> list[RuleSpec]:
    """Regras do catálogo restritas ao instrumento C (instrumento I fica não aplicável)."""
    return [r.model_copy(update={"instrumentos": ("C",)}) for r in carregar_regras()]


def executar(
    tmp_path: Path,
    cenario: CenarioRegras,
    *,
    regras: list[RuleSpec] | None = None,
    config: RunConfig | None = None,
    snapshot: SnapshotSet | None = None,
    derivar_selecao: bool = False,
) -> RunResult:
    dataset, insumos = materializar(cenario, tmp_path / "entrada")
    if derivar_selecao:
        insumos = replace(insumos, selecoes=None)
    return evaluate_rules(
        dataset,
        snapshot or snapshot_vazio(),
        regras if regras is not None else carregar_regras(),
        config or RunConfig(versao="1"),
        tmp_path / "saida",
        insumos=insumos,
    )


def saida(resultado: RunResult, schema_id: str) -> str:
    return next(ref.caminho for ref in resultado.saidas if ref.schema_id == schema_id)


def tabela(resultado: RunResult, schema_id: str) -> list[dict[str, Any]]:
    linhas: list[dict[str, Any]] = pq.read_table(saida(resultado, schema_id)).to_pylist()
    return linhas


def avaliacoes_por_chave(resultado: RunResult) -> dict[tuple[str, str], dict[str, Any]]:
    return {(a["row_id"], a["rule_id"]): a for a in tabela(resultado, "avaliacoes.v1")}
