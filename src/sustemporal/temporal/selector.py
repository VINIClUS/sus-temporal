"""Seleção explícita de versões por regra e fonte (T06)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts import ProductionRecord, RuleSpec, RunConfig, SnapshotSet


def select_snapshots(record: ProductionRecord, rule: RuleSpec, config: RunConfig) -> SnapshotSet:
    """Seleciona as versões exigidas pela regra ou registra a abstenção."""
    raise NotImplementedError
