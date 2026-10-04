"""Motor integrado à seleção temporal em lote do T06 (`selecao_versoes.v1` e `SnapshotSet`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, RuleSpec, RunConfig, SnapshotSet
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.rules.insumos import InsumosAvaliacao
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["SelecaoEmLote", "avaliar_com_registro", "selecionar_em_lote"]


@dataclass(frozen=True)
class SelecaoEmLote:
    """Seleção gravada (`DatasetRef` com hash lógico) e o `SnapshotSet` da execução."""

    selecoes: DatasetRef
    snapshots: SnapshotSet


def selecionar_em_lote(
    dataset: DatasetRef,
    regras: list[RuleSpec],
    config: RunConfig,
    registro: RegistroTemporal,
    destino: Path,
    *,
    insumos: InsumosAvaliacao | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> SelecaoEmLote:
    raise NotImplementedError


def avaliar_com_registro(
    dataset: DatasetRef,
    regras: list[RuleSpec],
    config: RunConfig,
    registro: RegistroTemporal,
    out: Path,
    *,
    insumos: InsumosAvaliacao | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> RunResult:
    raise NotImplementedError
