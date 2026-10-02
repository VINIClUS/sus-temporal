"""Seleção explícita de versões por regra e fonte (T06)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts import ProductionRecord, RuleSpec, RunConfig, SnapshotSet
    from sustemporal.contracts.base import FamiliaFonte
    from sustemporal.contracts.temporal import (
        BaseTemporal,
        CompetenciaArquivo,
        CriterioTemporal,
        PoliticaTemporal,
        SelecaoVersao,
    )
    from sustemporal.temporal.registry import RegistroTemporal


def selecionar_versao(
    registro: RegistroTemporal,
    criterio: CriterioTemporal,
    competencia: CompetenciaArquivo,
    *,
    uf: str | None = None,
    corte: datetime | None = None,
) -> SelecaoVersao:
    """Decide a versão de uma fonte para uma competência exata, ou a abstenção."""
    raise NotImplementedError


def nao_resolvida(
    fonte: FamiliaFonte, motivo: str, base: BaseTemporal | None = None
) -> SelecaoVersao:
    raise NotImplementedError


def select_snapshots(
    record: ProductionRecord,
    rule: RuleSpec,
    config: RunConfig,
    *,
    registro: RegistroTemporal | None = None,
    politica: PoliticaTemporal | None = None,
    politicas: Path | None = None,
) -> SnapshotSet:
    """Seleciona as versões exigidas pela regra ou registra a abstenção."""
    raise NotImplementedError
