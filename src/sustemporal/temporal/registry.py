"""Registro temporal: versões de conteúdo e histórico completo de observações (T06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion
    from sustemporal.contracts.base import FamiliaFonte
    from sustemporal.contracts.temporal import CompetenciaArquivo

__all__ = ["ORIGEM_INTERVALO", "IntervaloObservado", "RegistroTemporal"]

ORIGEM_INTERVALO = "OBSERVACAO_DA_PESQUISA"


@dataclass(frozen=True)
class IntervaloObservado:
    """Sequência contígua de observações do mesmo conteúdo, segundo a coleta da pesquisa.

    Não é histórico oficial de publicação: só diz quando a pesquisa viu o conteúdo.
    """

    artifact_id: str
    primeira_observacao: datetime
    ultima_observacao: datetime
    observation_ids: tuple[str, ...]
    origem: str = ORIGEM_INTERVALO


@dataclass(frozen=True)
class RegistroTemporal:
    observacoes: tuple[ArtifactObservation, ...]
    versoes: Mapping[str, ArtifactVersion]
    partes_esperadas: Mapping[tuple[FamiliaFonte, str], frozenset[str]] = field(
        default_factory=dict
    )

    @classmethod
    def de_manifesto(
        cls,
        caminho: Path,
        *,
        partes_esperadas: Mapping[tuple[FamiliaFonte, str], frozenset[str]] | None = None,
    ) -> RegistroTemporal:
        raise NotImplementedError

    def observacoes_de(
        self, fonte: FamiliaFonte, uf: str | None, competencia: CompetenciaArquivo
    ) -> tuple[ArtifactObservation, ...]:
        raise NotImplementedError

    def intervalos(
        self,
        fonte: FamiliaFonte,
        uf: str | None,
        competencia: CompetenciaArquivo,
        *,
        parte: str | None = None,
    ) -> list[IntervaloObservado]:
        raise NotImplementedError


def registro_de(
    observacoes: Iterable[ArtifactObservation], versoes: Iterable[ArtifactVersion]
) -> RegistroTemporal:
    raise NotImplementedError
